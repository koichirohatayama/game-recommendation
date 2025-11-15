"""類似度検索サービス向け DTO。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from game_recommendation.shared.types import DTO, Timestamp, utc_now

__all__ = [
    "SimilarityQuery",
    "EmbeddedGameContext",
    "SimilarityMatch",
    "SimilarityResult",
]


def _normalize_sequence(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _normalize_ids(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    normalized = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered not in normalized:
            normalized.append(lowered)
    return tuple(normalized)


@dataclass(slots=True)
class SimilarityQuery(DTO):
    """類似度検索に必要な情報を保持する入力 DTO。"""

    title: str
    summary: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    genres: tuple[str, ...] = field(default_factory=tuple)
    focus_keywords: tuple[str, ...] = field(default_factory=tuple)
    limit: int = 10
    game_id: str | None = None
    excluded_game_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.title.strip():
            msg = "title is required"
            raise ValueError(msg)
        if self.limit <= 0:
            msg = "limit must be a positive integer"
            raise ValueError(msg)
        object.__setattr__(self, "tags", _normalize_sequence(self.tags))
        object.__setattr__(self, "genres", _normalize_sequence(self.genres))
        object.__setattr__(self, "focus_keywords", _normalize_sequence(self.focus_keywords))
        object.__setattr__(self, "excluded_game_ids", _normalize_ids(self.excluded_game_ids))

    @property
    def normalized_tags(self) -> tuple[str, ...]:
        return tuple(tag.lower() for tag in self.tags)

    @property
    def normalized_genres(self) -> tuple[str, ...]:
        return tuple(genre.lower() for genre in self.genres)

    @property
    def normalized_keywords(self) -> tuple[str, ...]:
        return tuple(keyword.lower() for keyword in self.focus_keywords)


@dataclass(slots=True)
class EmbeddedGameContext(DTO):
    """埋め込みメタデータから再構築したゲーム情報。"""

    game_id: str
    title: str | None = None
    summary: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    genres: tuple[str, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", _normalize_sequence(self.tags))
        object.__setattr__(self, "genres", _normalize_sequence(self.genres))
        object.__setattr__(self, "keywords", _normalize_sequence(self.keywords))
        object.__setattr__(self, "extra", dict(self.extra))

    @property
    def normalized_tags(self) -> set[str]:
        return {tag.lower() for tag in self.tags}

    @property
    def normalized_genres(self) -> set[str]:
        return {genre.lower() for genre in self.genres}

    @property
    def normalized_keywords(self) -> set[str]:
        return {keyword.lower() for keyword in self.keywords}

    @classmethod
    def from_metadata(
        cls,
        game_id: str,
        metadata: Mapping[str, Any] | None,
    ) -> EmbeddedGameContext:
        payload = metadata or {}
        return cls(
            game_id=game_id,
            title=payload.get("title"),
            summary=payload.get("summary"),
            tags=tuple(payload.get("tags", ())),
            genres=tuple(payload.get("genres", ())),
            keywords=tuple(payload.get("keywords", ())),
            extra=payload,
        )


@dataclass(slots=True)
class SimilarityMatch(DTO):
    """最終的なスコア情報。"""

    candidate: EmbeddedGameContext
    score: float
    base_score: float
    distance: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(slots=True)
class SimilarityResult(DTO):
    """サービス呼び出し結果。"""

    query: SimilarityQuery
    matches: tuple[SimilarityMatch, ...]
    embedding_model: str
    computed_at: Timestamp = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matches", tuple(self.matches))
