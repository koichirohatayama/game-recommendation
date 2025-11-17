"""EmbeddedGamePayload のコンバータテスト。"""

from __future__ import annotations

import json
from array import array
from datetime import UTC, datetime

import pytest

from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.infra.igdb.dto import IGDBGameDTO


def _igdb_game() -> IGDBGameDTO:
    return IGDBGameDTO(
        id=123,
        name="Sample Game",
        slug="sample-game",
        summary="A hero saves the world.",
        storyline="A long tale about the hero.",
        first_release_date=datetime(2024, 1, 2, tzinfo=UTC),
        cover_image_id="cover123",
        platforms=(6,),
        category=0,
        tags=(10, 20),
    )


def _embedding() -> IngestedEmbedding:
    return IngestedEmbedding(
        title_embedding=(0.1, 0.2, 0.3),
        storyline_embedding=(0.2, 0.3, 0.4),
        summary_embedding=(0.3, 0.4, 0.5),
        model="test-encoder",
        metadata={"provider": "fake"},
    )


def _tags() -> list[GameTagPayload]:
    return [
        GameTagPayload(slug="rpg", label="RPG", tag_class="genre", igdb_id=10),
        GameTagPayload(slug="fantasy", label="Fantasy", tag_class="keyword"),
        GameTagPayload(slug="rpg", label="Role Playing", tag_class="genre"),
    ]


def test_to_igdb_game_builds_insertable_payload() -> None:
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline="Long description",
        summary="Short story",
        checksum="checksum123",
        cover_url="https://example.com/cover.png",
        tags=_tags(),
        keywords=("hero", "adventure"),
    )

    result = payload.to_igdb_game()

    assert result.igdb_id == 123
    assert result.title == "Sample Game"
    assert result.description == "Long description"
    assert result.summary == "Short story"
    assert result.release_date == "2024-01-02"
    assert result.cover_url == "https://example.com/cover.png"
    cache = json.loads(result.tags_cache)
    assert set(cache["tags"]) == {"RPG", "Fantasy"}
    assert cache["keywords"] == ["hero", "adventure"]


def test_to_game_embedding_merges_metadata() -> None:
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        embedding=_embedding(),
        tags=_tags(),
        keywords=("switch",),
    )

    result = payload.to_game_embedding()

    assert result.game_id == "123"
    assert result.dimension == 3
    title_vec = array("f")
    title_vec.frombytes(result.title_embedding)
    assert tuple(title_vec) == pytest.approx((0.1, 0.2, 0.3))
    storyline_vec = array("f")
    storyline_vec.frombytes(result.storyline_embedding)
    assert tuple(storyline_vec) == pytest.approx((0.2, 0.3, 0.4))
    summary_vec = array("f")
    summary_vec.frombytes(result.summary_embedding)
    assert tuple(summary_vec) == pytest.approx((0.3, 0.4, 0.5))
    metadata = result.embedding_metadata
    assert metadata["title"] == "Sample Game"
    assert metadata["storyline"] == "A long tale about the hero."
    assert metadata["summary"] == "A hero saves the world."
    assert "tags" in metadata and "keywords" in metadata
    assert metadata["provider"] == "fake"


def test_to_game_tag_and_link_payloads() -> None:
    payload = EmbeddedGamePayload(igdb_game=_igdb_game(), tags=_tags())
    tags = payload.to_game_tag()

    assert len(tags) == 2
    lookup = {(tag.slug, tag.tag_class): idx + 1 for idx, tag in enumerate(tags)}

    links = payload.to_game_tag_link(game_record_id=42, tag_id_lookup=lookup)

    assert len(links) == 2
    assert all(link.game_id == 42 for link in links)
    assert {link.tag_id for link in links} == {1, 2}


def test_to_game_tag_link_raises_for_missing_tag() -> None:
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(), tags=[GameTagPayload(slug="rpg", label="RPG", tag_class="genre")]
    )

    with pytest.raises(KeyError):
        payload.to_game_tag_link(game_record_id=1, tag_id_lookup={})


def test_to_user_favorite_game_prefers_argument_notes() -> None:
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        favorite=True,
        favorite_notes="pre-set",
    )

    result = payload.to_user_favorite_game(game_record_id=9, notes=" from user ")

    assert result.game_id == 9
    assert result.notes == "from user"
