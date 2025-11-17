from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

from game_recommendation.core.favorites.loader import FavoriteLoader
from game_recommendation.infra.db.models import (
    GameEmbedding,
    GameTag,
    GameTagLink,
    IgdbGame,
    UserFavoriteGame,
)
from game_recommendation.infra.db.session import DatabaseSessionManager
from game_recommendation.infra.db.sqlite_vec import _embedding_to_blob
from game_recommendation.shared.config import (
    AppSettings,
    DiscordSettings,
    GeminiSettings,
    IGDBSettings,
    StorageSettings,
)


@pytest.fixture()
def db_manager(tmp_path: Path) -> DatabaseSessionManager:
    settings = AppSettings(
        igdb=IGDBSettings(client_id="cid", client_secret=SecretStr("secret")),
        discord=DiscordSettings(webhook_url="https://example.com", webhook_username="bot"),
        gemini=GeminiSettings(api_key=SecretStr("api"), model="embedding-test"),
        storage=StorageSettings(sqlite_path=tmp_path / "favorites.sqlite"),
    )
    manager = DatabaseSessionManager(db_path=tmp_path / "favorites.sqlite", settings=settings)
    manager.initialize_schema()
    yield manager
    manager.close()


def test_load_returns_embedded_payload(db_manager: DatabaseSessionManager) -> None:
    loader = FavoriteLoader(db_manager.session_factory)

    with db_manager.session_factory.begin() as session:
        game = IgdbGame(
            igdb_id=123,
            slug="demo-game",
            title="Demo Game",
            description="Long description",
            tags_cache=json.dumps({"keywords": ["Co-Op", "RPG"]}),
            release_date="2024-01-05",
            cover_url="https://example.com/cover.jpg",
            summary="Short",
            checksum="abc123",
        )
        session.add(game)
        session.flush()

        tag = GameTag(slug="rpg", label="RPG", tag_class="genre", igdb_id=10)
        session.add(tag)
        session.flush()
        session.add(GameTagLink(game_id=int(game.id), tag_id=int(tag.id)))

        session.add(UserFavoriteGame(game_id=int(game.id), notes="must play"))

        session.add(
            GameEmbedding(
                game_id=str(game.igdb_id),
                dimension=2,
                title_embedding=_embedding_to_blob((0.1, 0.2)),
                storyline_embedding=_embedding_to_blob((0.3, 0.4)),
                summary_embedding=_embedding_to_blob((0.5, 0.6)),
                embedding_metadata={"model": "test-model", "keywords": ["Co-Op"]},
            )
        )

    payloads = loader.load()

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.favorite is True
    assert payload.favorite_notes == "must play"
    assert payload.igdb_game.id == 123
    assert payload.igdb_game.slug == "demo-game"
    assert payload.igdb_game.first_release_date == datetime(2024, 1, 5)
    assert payload.release_date == "2024-01-05"
    assert payload.keywords == ("Co-Op", "RPG")
    assert payload.tags[0].slug == "rpg"

    embedding = payload.embedding
    assert embedding is not None
    assert embedding.model == "test-model"
    assert embedding.title_embedding == pytest.approx((0.1, 0.2))
    assert embedding.storyline_embedding == pytest.approx((0.3, 0.4))
    assert embedding.summary_embedding == pytest.approx((0.5, 0.6))
    assert embedding.dimension == 2


def test_load_handles_missing_embedding_and_keywords(db_manager: DatabaseSessionManager) -> None:
    loader = FavoriteLoader(db_manager.session_factory)

    with db_manager.session_factory.begin() as session:
        game = IgdbGame(
            igdb_id=456,
            slug="no-embed",
            title="No Embed",
            description="Desc",
            tags_cache="not-json",
            release_date="not-a-date",
        )
        session.add(game)
        session.flush()

        session.add(UserFavoriteGame(game_id=int(game.id), notes=None))

    payloads = loader.load()

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.embedding is None
    assert payload.tags == ()
    assert payload.keywords == ()
    assert payload.igdb_game.first_release_date is None
