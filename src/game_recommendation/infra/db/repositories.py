"""ゲームタグ向けのリポジトリ実装。"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from game_recommendation.core.ingest.tag_resolver import GameTagRepositoryProtocol
from game_recommendation.infra.db.models import GameTag


class SQLAlchemyGameTagRepository(GameTagRepositoryProtocol):
    """SQLAlchemy を用いた game_tags テーブルの DAO。"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def fetch_by_igdb_ids(self, *, tag_class: str, igdb_ids: Sequence[int]) -> dict[int, GameTag]:
        if not igdb_ids:
            return {}

        with self._session_factory() as session:
            stmt = select(GameTag).where(
                GameTag.tag_class == tag_class, GameTag.igdb_id.in_(list(igdb_ids))
            )
            rows = session.scalars(stmt).all()

        return {int(row.igdb_id): row for row in rows if row.igdb_id is not None}

    def save_all(self, tags: Sequence[GameTag]) -> None:
        if not tags:
            return

        with self._session_factory.begin() as session:
            for tag in tags:
                session.add(tag)


__all__ = ["SQLAlchemyGameTagRepository"]
