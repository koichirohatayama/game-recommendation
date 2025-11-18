from __future__ import annotations

import pytest

from game_recommendation.core.favorites.query import (
    DiceTagSimilarity,
    FavoritesQuery,
    FavoritesQueryError,
)
from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.infra.igdb.dto import IGDBGameDTO


def _make_payload(
    game_id: int,
    *,
    tags: tuple[GameTagPayload, ...] = (),
    embedding: IngestedEmbedding | None = None,
) -> EmbeddedGamePayload:
    return EmbeddedGamePayload(
        igdb_game=IGDBGameDTO(id=game_id, name=f"Game {game_id}", slug=f"game-{game_id}"),
        storyline="desc",
        summary="desc",
        checksum=None,
        cover_url=None,
        tags=tags,
        keywords=(),
        embedding=embedding,
        favorite=True,
        favorite_notes=None,
    )


def _make_embedding(values: tuple[float, ...]) -> IngestedEmbedding:
    return IngestedEmbedding(
        title_embedding=values,
        storyline_embedding=tuple(value * 2 for value in values),
        summary_embedding=tuple(value * 3 for value in values),
        model="unit-test",
    )


def test_filter_by_tags_and_limit() -> None:
    target_tags = ("genre", 1), ("theme", 2)

    payloads = (
        _make_payload(
            1,
            tags=(
                GameTagPayload(slug="rpg", label="RPG", tag_class="genre", igdb_id=1),
                GameTagPayload(slug="dark", label="Dark", tag_class="theme", igdb_id=2),
            ),
        ),
        _make_payload(
            2,
            tags=(GameTagPayload(slug="rpg", label="RPG", tag_class="genre", igdb_id=1),),
        ),
        _make_payload(
            3,
            tags=(GameTagPayload(slug="action", label="Action", tag_class="genre", igdb_id=3),),
        ),
    )

    results = FavoritesQuery(payloads).filter_by_tags(target_tags).limit(1).get()

    assert [payload.igdb_game.id for payload in results] == [1]


def test_tag_similarity_sorting_allows_strategy_override() -> None:
    target_tags = ("genre", 1), ("feature", 10)

    payloads = (
        _make_payload(
            1,
            tags=(
                GameTagPayload(slug="rpg", label="RPG", tag_class="genre", igdb_id=1),
                GameTagPayload(slug="coop", label="Co-op", tag_class="feature", igdb_id=10),
            ),
        ),
        _make_payload(
            2,
            tags=(GameTagPayload(slug="rpg", label="RPG", tag_class="genre", igdb_id=1),),
        ),
        _make_payload(
            3,
            tags=(GameTagPayload(slug="solo", label="Solo", tag_class="feature", igdb_id=99),),
        ),
    )

    default_sorted = FavoritesQuery(payloads).sort_by_tag_similarity(target_tags).get()
    assert [payload.igdb_game.id for payload in default_sorted] == [1, 2, 3]

    class ReverseDice(DiceTagSimilarity):
        def compute(self, base: set[tuple[str, str]], candidate: set[tuple[str, str]]) -> float:
            return 1.0 - super().compute(base, candidate)

    reversed_sorted = (
        FavoritesQuery(payloads).sort_by_tag_similarity(target_tags, metric=ReverseDice()).get()
    )
    assert [payload.igdb_game.id for payload in reversed_sorted] == [3, 2, 1]


def test_title_embedding_similarity_orders_by_cosine() -> None:
    query_embedding = (1.0, 0.0)

    payloads = (
        _make_payload(1, embedding=_make_embedding((1.0, 0.0))),
        _make_payload(2, embedding=_make_embedding((0.5, 0.5))),
        _make_payload(3, embedding=None),
    )

    results = FavoritesQuery(payloads).sort_by_title_embedding(query_embedding).get()

    assert [payload.igdb_game.id for payload in results] == [1, 2, 3]


def test_storyline_embedding_usage_and_sort_chain_priority() -> None:
    payloads = (
        _make_payload(1, embedding=_make_embedding((0.1, 0.9))),
        _make_payload(2, embedding=_make_embedding((0.9, 0.1))),
    )

    class ReverseIdStrategy:
        def score(self, payload: EmbeddedGamePayload) -> float:
            return -float(payload.igdb_game.id)

    results = (
        FavoritesQuery(payloads)
        .sort_by_storyline_embedding((1.0, 0.0))
        .sort_with(ReverseIdStrategy())
        .get()
    )

    assert [payload.igdb_game.id for payload in results] == [1, 2]


def test_summary_embedding_similarity_orders_by_cosine() -> None:
    query_embedding = (1.0, 0.0)

    payloads = (
        _make_payload(1, embedding=_make_embedding((1.0, 0.0))),
        _make_payload(2, embedding=_make_embedding((0.5, 0.5))),
        _make_payload(3, embedding=None),
    )

    results = FavoritesQuery(payloads).sort_by_summary_embedding(query_embedding).get()

    assert [payload.igdb_game.id for payload in results] == [1, 2, 3]


def test_limit_requires_positive_value() -> None:
    query = FavoritesQuery((_make_payload(1),))
    with pytest.raises(FavoritesQueryError):
        query.limit(0)
