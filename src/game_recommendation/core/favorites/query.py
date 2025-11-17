"""お気に入り検索用のフィルタ・ソートチェーン。"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from game_recommendation.core.ingest.models import EmbeddedGamePayload, GameTagPayload
from game_recommendation.shared.exceptions import DomainError
from game_recommendation.shared.logging import get_logger

try:  # pragma: no cover - 型ヒント専用
    from structlog.stdlib import BoundLogger
except Exception:  # pragma: no cover
    BoundLogger = object  # type: ignore[assignment]


TagIdentifier = tuple[str, int]
TagKey = tuple[str, str]
FavoritesFilter = Callable[[EmbeddedGamePayload], bool]


class FavoritesQueryError(DomainError):
    """お気に入り検索ファサードの失敗を表す例外。"""

    default_message = "お気に入り検索に失敗しました"


class FavoritesSortStrategy(Protocol):
    """お気に入り結果をソートする戦略。"""

    def score(self, payload: EmbeddedGamePayload) -> float:
        """スコアの高い順に並べるための値を返す。"""


class TagSimilarityMetric(Protocol):
    """タグ類似度を算出するプロトコル。"""

    def compute(self, base: set[TagKey], candidate: set[TagKey]) -> float:
        """類似度を返す。"""


class JaccardTagSimilarity:
    """タグ集合のJaccard類似度。"""

    def compute(self, base: set[TagKey], candidate: set[TagKey]) -> float:
        union = base | candidate
        if not union:
            return 0.0
        return len(base & candidate) / len(union)


@dataclass(slots=True)
class TagSimilarityStrategy:
    """タグ類似度を用いたソート戦略。"""

    target_tags: set[TagKey]
    metric: TagSimilarityMetric = field(default_factory=JaccardTagSimilarity)

    def score(self, payload: EmbeddedGamePayload) -> float:
        candidate = _tag_keys_from_payload(payload.tags)
        if not self.target_tags or not candidate:
            return 0.0
        return self.metric.compute(self.target_tags, candidate)


@dataclass(slots=True)
class EmbeddingSimilarityStrategy:
    """埋め込み類似度を用いたソート戦略。"""

    query_vector: tuple[float, ...]
    selector: Callable[[EmbeddedGamePayload], Sequence[float] | None]
    missing_score: float = -math.inf

    def score(self, payload: EmbeddedGamePayload) -> float:
        vector = self.selector(payload)
        if vector is None:
            return self.missing_score
        return _cosine_similarity(self.query_vector, vector)


@dataclass(slots=True)
class FavoritesQuery:
    """フィルタとソートをチェーン適用するお気に入り検索。"""

    payloads: tuple[EmbeddedGamePayload, ...]
    filters: tuple[FavoritesFilter, ...] = field(default_factory=tuple)
    strategies: tuple[FavoritesSortStrategy, ...] = field(default_factory=tuple)
    limit_size: int | None = None
    logger: BoundLogger = field(
        default_factory=lambda: get_logger(__name__, component="favorites-query")
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "payloads", tuple(self.payloads))

    def filter_by_tags(self, tag_identifiers: Sequence[TagIdentifier]) -> FavoritesQuery:
        """タグ(class+IGDB ID)をすべて含むものだけに絞り込む。"""

        normalized = _normalize_tag_identifiers(tag_identifiers)
        if not normalized:
            return self

        def predicate(payload: EmbeddedGamePayload) -> bool:
            return normalized.issubset(_tag_keys_from_payload(payload.tags))

        return self._clone(filters=self.filters + (predicate,))

    def limit(self, limit: int) -> FavoritesQuery:
        """最大件数を設定する。"""

        if limit <= 0:
            msg = "limitは1以上を指定してください"
            raise FavoritesQueryError(msg)
        return self._clone(limit_size=limit)

    def sort_with(self, strategy: FavoritesSortStrategy) -> FavoritesQuery:
        """任意のソート戦略を追加する。"""

        return self._clone(strategies=self.strategies + (strategy,))

    def sort_by_tag_similarity(
        self,
        tag_identifiers: Sequence[TagIdentifier],
        *,
        metric: TagSimilarityMetric | None = None,
    ) -> FavoritesQuery:
        """タグ類似度(Jaccardなど)でソートする。"""

        target = _normalize_tag_identifiers(tag_identifiers)
        strategy = TagSimilarityStrategy(
            target_tags=target, metric=metric or JaccardTagSimilarity()
        )
        return self.sort_with(strategy)

    def sort_by_title_embedding(self, embedding: Sequence[float]) -> FavoritesQuery:
        """タイトル埋め込みとのコサイン類似度でソートする。"""

        vector = _normalize_vector(embedding)
        strategy = EmbeddingSimilarityStrategy(vector, selector=_extract_title_embedding)
        return self.sort_with(strategy)

    def sort_by_storyline_embedding(self, embedding: Sequence[float]) -> FavoritesQuery:
        """ストーリー埋め込みとのコサイン類似度でソートする。"""

        vector = _normalize_vector(embedding)
        strategy = EmbeddingSimilarityStrategy(vector, selector=_extract_storyline_embedding)
        return self.sort_with(strategy)

    def sort_by_summary_embedding(self, embedding: Sequence[float]) -> FavoritesQuery:
        """サマリー埋め込みとのコサイン類似度でソートする。"""

        vector = _normalize_vector(embedding)
        strategy = EmbeddingSimilarityStrategy(vector, selector=_extract_summary_embedding)
        return self.sort_with(strategy)

    def get(self) -> list[EmbeddedGamePayload]:
        """チェーンされたフィルタとソートを適用した結果を返す。"""

        results: list[EmbeddedGamePayload] = list(self.payloads)
        for predicate in self.filters:
            results = [payload for payload in results if predicate(payload)]

        for strategy in self.strategies:
            results = sorted(
                results, key=lambda payload: _safe_score(strategy, payload), reverse=True
            )

        if self.limit_size is not None:
            results = results[: self.limit_size]
        return results

    def _clone(
        self,
        *,
        filters: tuple[FavoritesFilter, ...] | None = None,
        strategies: tuple[FavoritesSortStrategy, ...] | None = None,
        limit_size: int | None = None,
    ) -> FavoritesQuery:
        return FavoritesQuery(
            payloads=self.payloads,
            filters=filters or self.filters,
            strategies=strategies or self.strategies,
            limit_size=self.limit_size if limit_size is None else limit_size,
            logger=self.logger,
        )


def _normalize_tag_identifiers(tag_identifiers: Sequence[TagIdentifier]) -> set[TagKey]:
    normalized: set[TagKey] = set()
    for tag_class, igdb_id in tag_identifiers:
        key = _tag_key(tag_class=tag_class, igdb_id=igdb_id)
        if key:
            normalized.add(key)
    return normalized


def _tag_key(tag_class: str, igdb_id: int | None, slug: str | None = None) -> TagKey | None:
    normalized_class = tag_class.strip().lower()
    if igdb_id is not None:
        return (normalized_class, str(int(igdb_id)))
    if slug:
        return (normalized_class, slug.strip().lower())
    return None


def _tag_keys_from_payload(tags: Sequence[GameTagPayload]) -> set[TagKey]:
    keys: set[TagKey] = set()
    for tag in tags:
        key = _tag_key(tag.tag_class, tag.igdb_id, tag.slug)
        if key:
            keys.add(key)
    return keys


def _normalize_vector(values: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if not vector:
        msg = "類似度計算には1次元以上のベクトルが必要です"
        raise FavoritesQueryError(msg)
    return vector


def _cosine_similarity(base: Sequence[float], target: Sequence[float]) -> float:
    base_values = tuple(float(value) for value in base)
    target_values = tuple(float(value) for value in target)
    if not base_values or not target_values or len(base_values) != len(target_values):
        return -math.inf

    dot = sum(x * y for x, y in zip(base_values, target_values, strict=False))
    norm_base = math.sqrt(sum(value * value for value in base_values))
    norm_target = math.sqrt(sum(value * value for value in target_values))
    if norm_base == 0 or norm_target == 0:
        return -math.inf
    return dot / (norm_base * norm_target)


def _safe_score(strategy: FavoritesSortStrategy, payload: EmbeddedGamePayload) -> float:
    try:
        score = float(strategy.score(payload))
    except Exception:
        return -math.inf

    if math.isnan(score):
        return -math.inf
    return score


def _extract_title_embedding(payload: EmbeddedGamePayload) -> Sequence[float] | None:
    embedding = payload.embedding
    if embedding is None:
        return None
    return embedding.title_embedding


def _extract_storyline_embedding(payload: EmbeddedGamePayload) -> Sequence[float] | None:
    embedding = payload.embedding
    if embedding is None:
        return None
    return embedding.storyline_embedding


def _extract_summary_embedding(payload: EmbeddedGamePayload) -> Sequence[float] | None:
    embedding = payload.embedding
    if embedding is None:
        return None
    return embedding.summary_embedding


__all__ = [
    "FavoritesQuery",
    "FavoritesQueryError",
    "FavoritesSortStrategy",
    "TagSimilarityMetric",
    "JaccardTagSimilarity",
    "TagSimilarityStrategy",
    "EmbeddingSimilarityStrategy",
]
