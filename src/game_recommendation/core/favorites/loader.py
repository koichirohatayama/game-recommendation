"""お気に入りゲームの統合モデルローダー。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.infra.db.models import (
    GameEmbedding,
    GameTag,
    GameTagLink,
    IgdbGame,
    UserFavoriteGame,
)
from game_recommendation.infra.db.sqlite_vec import SQLiteVecError, _blob_to_embedding
from game_recommendation.infra.igdb.dto import IGDBGameDTO
from game_recommendation.shared.exceptions import DomainError
from game_recommendation.shared.logging import get_logger

try:  # pragma: no cover - 型ヒント専用
    from structlog.stdlib import BoundLogger
except Exception:  # pragma: no cover
    BoundLogger = object  # type: ignore[assignment]


class FavoriteLoaderError(DomainError):
    """お気に入りローダーの失敗を表すエラー。"""

    default_message = "お気に入りデータの取得に失敗しました"


@dataclass(slots=True)
class FavoriteLoader:
    """DB からお気に入りゲームを統合モデルとして取得する。"""

    session_factory: Callable[[], Session]
    logger: BoundLogger = field(
        default_factory=lambda: get_logger(__name__, component="favorites-loader")
    )

    def load(self) -> list[EmbeddedGamePayload]:
        """お気に入りゲームの一覧を取得する。"""

        try:
            with self.session_factory() as session:
                records = session.execute(
                    select(UserFavoriteGame, IgdbGame).join(
                        IgdbGame, UserFavoriteGame.game_id == IgdbGame.id
                    )
                ).all()

                payloads: list[EmbeddedGamePayload] = []
                for favorite, game in records:
                    payloads.append(self._build_payload(session, favorite, game))

            self.logger.info("favorite_loader.loaded", count=len(payloads))
            return payloads
        except FavoriteLoaderError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.logger.error("favorite_loader.failed", error=str(exc))
            raise FavoriteLoaderError(str(exc)) from exc

    def _build_payload(
        self,
        session: Session,
        favorite: UserFavoriteGame,
        game: IgdbGame,
    ) -> EmbeddedGamePayload:
        tags = self._load_tags(session, int(game.id))
        keywords = self._load_keywords(game.tags_cache)
        embedding = self._load_embedding(session, game.igdb_id)

        igdb_game = IGDBGameDTO(
            id=int(game.igdb_id),
            name=game.title,
            slug=game.slug,
            summary=game.summary,
            first_release_date=self._parse_release_date(game.release_date),
            cover_image_id=None,
            platforms=(),
            category=None,
            tags=(),
        )

        return EmbeddedGamePayload(
            igdb_game=igdb_game,
            description=game.description,
            checksum=game.checksum,
            cover_url=game.cover_url,
            tags=tags,
            keywords=keywords,
            embedding=embedding,
            favorite=True,
            favorite_notes=favorite.notes,
        )

    def _load_tags(self, session: Session, game_record_id: int) -> tuple[GameTagPayload, ...]:
        rows = session.scalars(
            select(GameTag)
            .join(GameTagLink, GameTagLink.tag_id == GameTag.id)
            .where(GameTagLink.game_id == game_record_id)
            .order_by(GameTag.id)
        ).all()

        return tuple(
            GameTagPayload(
                slug=row.slug,
                label=row.label,
                tag_class=row.tag_class,
                igdb_id=row.igdb_id,
            )
            for row in rows
        )

    def _load_keywords(self, tags_cache: str | None) -> tuple[str, ...]:
        if not tags_cache:
            return ()

        try:
            payload = json.loads(tags_cache)
        except json.JSONDecodeError as exc:
            self.logger.warning("favorite_loader.tags_cache_invalid", error=str(exc))
            return ()

        keywords = payload.get("keywords") or ()
        return tuple(
            keyword.strip() for keyword in keywords if isinstance(keyword, str) and keyword.strip()
        )

    def _load_embedding(
        self,
        session: Session,
        igdb_id: int,
    ) -> IngestedEmbedding | None:
        record = session.scalar(select(GameEmbedding).where(GameEmbedding.game_id == str(igdb_id)))
        if record is None:
            self.logger.info("favorite_loader.embedding_missing", igdb_id=igdb_id)
            return None

        metadata = record.embedding_metadata or {}
        if not isinstance(metadata, dict):
            try:
                metadata = json.loads(str(metadata))
            except json.JSONDecodeError:
                metadata = {}

        model = str(metadata.get("model", "unknown")).strip() or "unknown"
        try:
            title_embedding = _blob_to_embedding(record.title_embedding, record.dimension)
            description_embedding = _blob_to_embedding(
                record.description_embedding, record.dimension
            )
        except SQLiteVecError as exc:
            raise FavoriteLoaderError(str(exc)) from exc

        return IngestedEmbedding(
            title_embedding=title_embedding,
            description_embedding=description_embedding,
            model=model,
            metadata=metadata,
            dimension=record.dimension,
        )

    def _parse_release_date(self, value: str | None) -> datetime | None:
        if not value:
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            self.logger.warning("favorite_loader.invalid_release_date", value=value)
            return None


__all__ = ["FavoriteLoader", "FavoriteLoaderError"]
