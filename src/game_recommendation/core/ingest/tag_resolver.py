"""IGDB タグを game_tags に解決するサービス。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from game_recommendation.infra.db.models import GameTag
from game_recommendation.infra.igdb.dto import IGDBTagDTO
from game_recommendation.shared.exceptions import BaseAppError, DomainError, Result
from game_recommendation.shared.logging import get_logger
from game_recommendation.shared.types import ValueObject

try:  # pragma: no cover - 型ヒント専用
    from structlog.stdlib import BoundLogger
except Exception:  # pragma: no cover
    BoundLogger = object  # type: ignore[assignment]

_TAG_ID_MASK = (1 << 28) - 1
_TAG_TYPE_CLASS = {
    0: "theme",
    1: "genre",
    2: "keyword",
    4: "player_perspective",
}


class GameTagRepositoryProtocol(Protocol):
    """game_tags テーブルを扱うためのプロトコル。"""

    def fetch_by_igdb_ids(
        self, *, tag_class: str, igdb_ids: Sequence[int]
    ) -> Mapping[int, GameTag]:
        """IGDB ID とタグ種別で既存レコードを取得する。"""

    def save_all(self, tags: Sequence[GameTag]) -> None:
        """新規タグを一括保存する。"""


class TagClientProtocol(Protocol):
    """IGDB タグ取得用クライアントのプロトコル。"""

    def fetch_tags(self, *, tag_class: str, igdb_ids: Sequence[int]) -> Sequence[IGDBTagDTO]:
        """タグを取得する。"""


class TagResolverError(DomainError):
    """タグ解決時のエラー。"""

    default_message = "タグの解決に失敗しました"


@dataclass(slots=True)
class ResolvedTag(ValueObject):
    """解決済みタグの出力 DTO。"""

    tag_number: int
    slug: str
    label: str
    tag_class: str
    igdb_id: int


@dataclass(slots=True)
class _TagSpec:
    tag_number: int
    igdb_id: int
    tag_class: str


@dataclass(slots=True)
class TagResolver:
    """game_tags キャッシュを参照しつつ IGDB タグを解決する。"""

    repository: GameTagRepositoryProtocol
    igdb_client: TagClientProtocol
    logger: BoundLogger = field(
        default_factory=lambda: get_logger(__name__, component="tag-resolver")
    )

    def resolve(
        self, tag_numbers: Sequence[int]
    ) -> Result[tuple[ResolvedTag, ...], TagResolverError]:
        specs = [
            spec for tag_number in tag_numbers if (spec := self._decode_tag_number(tag_number))
        ]
        if not specs:
            return Result.ok(())

        resolved_records: dict[tuple[str, int], GameTag] = {}
        grouped_ids = self._group_by_class(specs)

        for tag_class, igdb_ids in grouped_ids.items():
            cached = self.repository.fetch_by_igdb_ids(tag_class=tag_class, igdb_ids=igdb_ids)
            for igdb_id, record in cached.items():
                resolved_records[(tag_class, igdb_id)] = record

            missing = [tag_id for tag_id in igdb_ids if tag_id not in cached]
            if not missing:
                continue

            try:
                fetched = self.igdb_client.fetch_tags(tag_class=tag_class, igdb_ids=missing)
            except BaseAppError as exc:
                return self._fail("igdb_fetch_failed", exc)
            except Exception as exc:  # noqa: BLE001 - 想定外の例外も捕捉
                return self._fail("igdb_fetch_unexpected_error", exc)

            to_save: list[GameTag] = []
            for tag in fetched:
                if tag.id not in missing:
                    continue
                record = GameTag(
                    slug=self._normalize_slug(tag.slug, tag.name, tag.id),
                    label=tag.name,
                    tag_class=tag_class,
                    igdb_id=tag.id,
                )
                to_save.append(record)
                resolved_records[(tag_class, tag.id)] = record

            try:
                self.repository.save_all(to_save)
            except BaseAppError as exc:
                return self._fail("tag_save_failed", exc)
            except Exception as exc:  # noqa: BLE001
                return self._fail("tag_save_unexpected_error", exc)

            missing_ids = set(missing) - {record.igdb_id for record in to_save}
            if missing_ids:
                self.logger.warning(
                    "tag_resolver_missing_api_results",
                    tag_class=tag_class,
                    missing_ids=sorted(missing_ids),
                )

        resolved: list[ResolvedTag] = []
        seen: set[tuple[str, int]] = set()
        for spec in specs:
            key = (spec.tag_class, spec.igdb_id)
            if key in seen:
                continue
            record = resolved_records.get(key)
            if record is None:
                self.logger.warning(
                    "tag_resolver_record_missing", tag_class=spec.tag_class, igdb_id=spec.igdb_id
                )
                continue
            resolved.append(
                ResolvedTag(
                    tag_number=spec.tag_number,
                    slug=record.slug,
                    label=record.label,
                    tag_class=record.tag_class,
                    igdb_id=int(record.igdb_id),
                )
            )
            seen.add(key)

        self.logger.info("tag_resolver_resolved", requested=len(specs), resolved=len(resolved))
        return Result.ok(tuple(resolved))

    def _decode_tag_number(self, tag_number: int) -> _TagSpec | None:
        if not isinstance(tag_number, int) or tag_number < 0:
            return None

        tag_type = tag_number >> 28
        igdb_id = tag_number & _TAG_ID_MASK
        tag_class = _TAG_TYPE_CLASS.get(tag_type)
        if tag_class is None or igdb_id <= 0:
            self.logger.debug(
                "tag_resolver_invalid_tag",
                tag_number=tag_number,
                tag_type=tag_type,
            )
            return None
        return _TagSpec(tag_number=tag_number, igdb_id=igdb_id, tag_class=tag_class)

    def _group_by_class(self, specs: Sequence[_TagSpec]) -> dict[str, list[int]]:
        grouped: dict[str, list[int]] = {}
        for spec in specs:
            ids = grouped.setdefault(spec.tag_class, [])
            if spec.igdb_id not in ids:
                ids.append(spec.igdb_id)
        return grouped

    def _normalize_slug(self, slug: str | None, name: str, igdb_id: int) -> str:
        if slug:
            return slug
        normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return normalized or f"tag-{igdb_id}"

    def _fail(
        self, event: str, error: Exception
    ) -> Result[tuple[ResolvedTag, ...], TagResolverError]:
        self.logger.error(
            event,
            error_type=error.__class__.__name__,
            message=str(error),
        )
        return Result.err(TagResolverError(str(error)))


__all__ = [
    "GameTagRepositoryProtocol",
    "ResolvedTag",
    "TagClientProtocol",
    "TagResolver",
    "TagResolverError",
]
