"""IGDB統合ビルダー - 単一IDから統合データモデルを構築する。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.core.ingest.tag_resolver import (
    ResolvedTag,
    TagResolver,
)
from game_recommendation.infra.embeddings.base import (
    EmbeddingJob,
    EmbeddingServiceError,
    EmbeddingServiceProtocol,
    EmbeddingVector,
)
from game_recommendation.infra.igdb.client import (
    IGDBClientProtocol,
    IGDBQueryBuilder,
    IGDBResponseFormat,
)
from game_recommendation.infra.igdb.dto import IGDBGameDTO
from game_recommendation.shared.exceptions import BaseAppError, DomainError, Result
from game_recommendation.shared.logging import get_logger

try:  # pragma: no cover - 型ヒント専用
    from structlog.stdlib import BoundLogger
except Exception:  # pragma: no cover
    BoundLogger = object  # type: ignore[assignment]


class GameBuilderError(DomainError):
    """ゲーム統合ビルダー実行時のエラー。"""

    default_message = "ゲームデータの構築に失敗しました"


class CoverUrlResolverProtocol(Protocol):
    """カバー画像URLを解決するプロトコル。"""

    def resolve_cover_url(self, image_id: str | None) -> str | None:
        """IGDB image_id からカバー画像URLを生成する。"""


@dataclass(slots=True)
class GameBuilder:
    """単一IGDB IDから統合データモデルを構築するビルダー。

    IGDB APIからゲーム詳細を取得し、TagResolverでタグを解決し、
    Geminiで埋め込みを生成して、EmbeddedGamePayloadを返す。

    DB挿入は行わない（呼び出し元の責務）。
    """

    igdb_client: IGDBClientProtocol
    tag_resolver: TagResolver
    embedding_service: EmbeddingServiceProtocol
    cover_url_resolver: CoverUrlResolverProtocol | None = None
    logger: BoundLogger = field(
        default_factory=lambda: get_logger(__name__, component="game-builder")
    )

    def build(
        self,
        igdb_id: int,
        *,
        generate_embedding: bool = True,
    ) -> Result[EmbeddedGamePayload, GameBuilderError]:
        """単一IGDB IDから統合データモデルを構築する。

        Args:
            igdb_id: IGDBゲームID
            generate_embedding: 埋め込み生成を実行するか（デフォルト: True）

        Returns:
            成功時: EmbeddedGamePayload
            失敗時: GameBuilderError
        """
        self.logger.info("game_builder_start", igdb_id=igdb_id)

        # 1. IGDB APIからゲーム詳細を取得
        game_dto_result = self._fetch_game_detail(igdb_id)
        if game_dto_result.is_err:
            return Result.err(game_dto_result.unwrap_err())
        game_dto = game_dto_result.unwrap()

        # 2. タグ解決
        tags_result = self._resolve_tags(game_dto.tags)
        if tags_result.is_err:
            return Result.err(tags_result.unwrap_err())
        game_tag_payloads = tags_result.unwrap()

        # 3. カバー画像URL解決
        cover_url = self._resolve_cover_url(game_dto.cover_image_id)

        # 4. 埋め込み生成（オプション）
        embedding: IngestedEmbedding | None = None
        storyline = game_dto.storyline or game_dto.summary or game_dto.name
        summary = game_dto.summary or game_dto.storyline or game_dto.name
        if generate_embedding:
            embedding_result = self._generate_embedding(
                title=game_dto.name,
                storyline=storyline,
                summary=summary,
            )
            if embedding_result.is_err:
                return Result.err(embedding_result.unwrap_err())
            embedding = embedding_result.unwrap()

        # 5. 統合データモデルを構築
        payload = EmbeddedGamePayload(
            igdb_game=game_dto,
            storyline=storyline,
            summary=summary,
            checksum=None,  # checksumはIGDB APIから提供されない
            cover_url=cover_url,
            tags=game_tag_payloads,
            keywords=(),
            embedding=embedding,
            favorite=False,
            favorite_notes=None,
        )

        self.logger.info(
            "game_builder_success",
            igdb_id=igdb_id,
            tags_count=len(game_tag_payloads),
            has_embedding=embedding is not None,
        )
        return Result.ok(payload)

    def _fetch_game_detail(self, igdb_id: int) -> Result[IGDBGameDTO, GameBuilderError]:
        """IGDB APIからゲーム詳細を取得する。"""
        query = (
            IGDBQueryBuilder()
            .select(
                "id",
                "name",
                "slug",
                "summary",
                "storyline",
                "first_release_date",
                "cover.image_id",
                "platforms",
                "category",
                "tags",
            )
            .where(f"id = {igdb_id}")
            .limit(1)
            .build()
        )

        try:
            response = self.igdb_client.fetch_games(query, response_format=IGDBResponseFormat.JSON)
        except BaseAppError as exc:
            return self._fail("igdb_fetch_failed", igdb_id, exc)
        except Exception as exc:
            return self._fail("igdb_fetch_unexpected_error", igdb_id, exc)

        if not response.items:
            error = GameBuilderError(f"IGDB ID {igdb_id} が見つかりません")
            self.logger.warning("game_not_found", igdb_id=igdb_id)
            return Result.err(error)

        return Result.ok(response.items[0])

    def _resolve_tags(
        self, tag_numbers: Sequence[int]
    ) -> Result[tuple[GameTagPayload, ...], GameBuilderError]:
        """タグ番号を解決してGameTagPayloadに変換する。"""
        if not tag_numbers:
            return Result.ok(())

        resolved_result = self.tag_resolver.resolve(tag_numbers)
        if resolved_result.is_err:
            error = resolved_result.unwrap_err()
            return self._fail_from_error("tag_resolver_failed", error)

        resolved_tags = resolved_result.unwrap()
        game_tags = tuple(self._to_game_tag_payload(tag) for tag in resolved_tags)
        return Result.ok(game_tags)

    def _to_game_tag_payload(self, resolved_tag: ResolvedTag) -> GameTagPayload:
        """ResolvedTagをGameTagPayloadに変換する。"""
        return GameTagPayload(
            slug=resolved_tag.slug,
            label=resolved_tag.label,
            tag_class=resolved_tag.tag_class,
            igdb_id=resolved_tag.igdb_id,
        )

    def _resolve_cover_url(self, image_id: str | None) -> str | None:
        """カバー画像URLを解決する。"""
        if not image_id or not self.cover_url_resolver:
            return None
        return self.cover_url_resolver.resolve_cover_url(image_id)

    def _generate_embedding(
        self, *, title: str, storyline: str, summary: str
    ) -> Result[IngestedEmbedding, GameBuilderError]:
        """タイトルとストーリー／サマリーから埋め込みベクトルを生成する。"""
        title_job = EmbeddingJob(content=title)
        storyline_job = EmbeddingJob(content=storyline)
        summary_job = EmbeddingJob(content=summary)

        try:
            vectors = self.embedding_service.embed_many([title_job, storyline_job, summary_job])
        except EmbeddingServiceError as exc:
            return self._fail_from_error("embedding_generation_failed", exc)
        except Exception as exc:
            return self._fail_from_error("embedding_generation_unexpected_error", exc)

        if len(vectors) != 3:
            error = GameBuilderError("埋め込み生成が不完全です")
            self.logger.error("embedding_incomplete", expected=3, actual=len(vectors))
            return Result.err(error)

        title_vector = self._find_vector(vectors, title_job.job_id)
        storyline_vector = self._find_vector(vectors, storyline_job.job_id)
        summary_vector = self._find_vector(vectors, summary_job.job_id)

        if not title_vector or not storyline_vector or not summary_vector:
            error = GameBuilderError("埋め込みベクトルが見つかりません")
            self.logger.error(
                "embedding_missing",
                has_title=title_vector is not None,
                has_storyline=storyline_vector is not None,
                has_summary=summary_vector is not None,
            )
            return Result.err(error)

        embedding = IngestedEmbedding(
            title_embedding=title_vector.values,
            storyline_embedding=storyline_vector.values,
            summary_embedding=summary_vector.values,
            model=title_vector.model,
            metadata={"embedding_service": self.embedding_service.provider_name},
        )
        return Result.ok(embedding)

    def _find_vector(
        self, vectors: Sequence[EmbeddingVector], job_id: str
    ) -> EmbeddingVector | None:
        """ジョブIDからベクトルを検索する。"""
        for vector in vectors:
            if vector.job_id == job_id:
                return vector
        return None

    def _fail(
        self, event: str, igdb_id: int, error: Exception
    ) -> Result[IGDBGameDTO, GameBuilderError]:
        """エラーをログに記録してResult.errを返す。"""
        self.logger.error(
            event,
            igdb_id=igdb_id,
            error_type=error.__class__.__name__,
            message=str(error),
        )
        return Result.err(GameBuilderError(str(error)))

    def _fail_from_error(
        self, event: str, error: Exception
    ) -> (
        Result[tuple[GameTagPayload, ...], GameBuilderError]
        | Result[IngestedEmbedding, GameBuilderError]
    ):
        """既存エラーからGameBuilderErrorを生成する。"""
        self.logger.error(
            event,
            error_type=error.__class__.__name__,
            message=str(error),
        )
        return Result.err(GameBuilderError(str(error)))


@dataclass(slots=True)
class DefaultCoverUrlResolver(CoverUrlResolverProtocol):
    """IGDB画像URLのデフォルト実装。"""

    base_url: str = "https://images.igdb.com/igdb/image/upload"
    size: str = "t_cover_big"

    def resolve_cover_url(self, image_id: str | None) -> str | None:
        """IGDB image_id からカバー画像URLを生成する。

        Format: https://images.igdb.com/igdb/image/upload/{size}/{image_id}.jpg
        """
        if not image_id:
            return None
        return f"{self.base_url}/{self.size}/{image_id}.jpg"


__all__ = [
    "CoverUrlResolverProtocol",
    "DefaultCoverUrlResolver",
    "GameBuilder",
    "GameBuilderError",
]
