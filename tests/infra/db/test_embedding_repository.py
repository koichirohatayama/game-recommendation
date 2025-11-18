'"""埋め込み DAO の骨組みテスト。"""'

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from game_recommendation.infra.db import (
    DatabaseSessionManager,
    GameEmbeddingPayload,
    SQLAlchemyEmbeddingRepository,
    seed_embeddings,
)
from game_recommendation.shared.config import (
    AppSettings,
    DiscordSettings,
    GeminiSettings,
    IGDBSettings,
    StorageSettings,
)

DIMENSION = 768


@pytest.fixture()
def app_settings(tmp_path: Path) -> AppSettings:
    db_path = tmp_path / "game_embeddings.sqlite"
    return AppSettings(
        igdb=IGDBSettings(client_id="cid", client_secret=SecretStr("secret")),
        discord=DiscordSettings(webhook_url="https://example.com", webhook_username="bot"),
        gemini=GeminiSettings(api_key=SecretStr("api"), model="embedding-test"),
        storage=StorageSettings(sqlite_path=db_path),
    )


@pytest.fixture()
def session_manager(
    tmp_path: Path,
    app_settings: AppSettings,
) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(
        db_path=tmp_path / "game_embeddings.sqlite",
        settings=app_settings,
    )
    manager.initialize_schema()
    yield manager
    manager.close()


@pytest.fixture()
def repository(session_manager: DatabaseSessionManager) -> SQLAlchemyEmbeddingRepository:
    return SQLAlchemyEmbeddingRepository(
        session_manager,
        dimension=DIMENSION,
    )


def _make_vector(seed: float) -> tuple[float, ...]:
    base = [seed + (i % 5) * 0.001 for i in range(DIMENSION)]
    return tuple(base)


def test_upsert_and_get_embedding_roundtrip(
    repository: SQLAlchemyEmbeddingRepository,
) -> None:
    payload = GameEmbeddingPayload(
        game_id="game-1",
        title_embedding=_make_vector(0.1),
        storyline_embedding=_make_vector(0.2),
        summary_embedding=_make_vector(0.3),
        metadata={"title": "Demo"},
    )

    inserted = repository.upsert_embedding(payload)
    reloaded = repository.get_embedding("game-1")
    assert reloaded is not None

    assert inserted.game_id == "game-1"
    assert inserted.title_embedding == pytest.approx(payload.title_embedding)
    assert inserted.storyline_embedding == pytest.approx(payload.storyline_embedding)
    assert inserted.summary_embedding == pytest.approx(payload.summary_embedding)
    assert inserted.dimension == DIMENSION
    assert reloaded.title_embedding == pytest.approx(payload.title_embedding)
    assert reloaded.storyline_embedding == pytest.approx(payload.storyline_embedding)
    assert reloaded.summary_embedding == pytest.approx(payload.summary_embedding)
    assert reloaded.metadata["title"] == "Demo"

    updated = repository.upsert_embedding(
        GameEmbeddingPayload(
            game_id="game-1",
            title_embedding=_make_vector(0.12),
            storyline_embedding=_make_vector(0.22),
            summary_embedding=_make_vector(0.25),
            metadata={"title": "Updated"},
        )
    )

    assert updated.updated_at >= inserted.updated_at
    assert updated.metadata["title"] == "Updated"


def test_search_similar_runs_full_scan(
    repository: SQLAlchemyEmbeddingRepository,
) -> None:
    seed_embeddings(
        repository,
        (
            GameEmbeddingPayload(
                game_id="a",
                title_embedding=_make_vector(0.1),
                storyline_embedding=_make_vector(0.0),
                summary_embedding=_make_vector(0.0),
                metadata={"title": "A"},
            ),
            GameEmbeddingPayload(
                game_id="b",
                title_embedding=_make_vector(0.2),
                storyline_embedding=_make_vector(0.2),
                summary_embedding=_make_vector(0.2),
                metadata={"title": "B"},
            ),
            GameEmbeddingPayload(
                game_id="c",
                title_embedding=_make_vector(0.5),
                storyline_embedding=_make_vector(0.5),
                summary_embedding=_make_vector(0.5),
                metadata={"title": "C"},
            ),
        ),
    )

    results = repository.search_similar(_make_vector(0.2), limit=2)

    assert len(results) == 2
    assert results[0].game_id == "b"
    assert results[0].distance <= results[1].distance
    assert {res.game_id for res in results}.issubset({"a", "b", "c"})


def test_seed_embeddings_helper_returns_records(
    repository: SQLAlchemyEmbeddingRepository,
) -> None:
    stored = seed_embeddings(
        repository,
        (
            GameEmbeddingPayload(
                game_id="seed-1",
                title_embedding=_make_vector(0.0),
                storyline_embedding=_make_vector(0.4),
                summary_embedding=_make_vector(0.4),
                metadata={"genre": "RPG"},
            ),
            GameEmbeddingPayload(
                game_id="seed-2",
                title_embedding=_make_vector(0.1),
                storyline_embedding=_make_vector(0.1),
                summary_embedding=_make_vector(0.1),
                metadata={"genre": "ARPG"},
            ),
        ),
    )

    assert [item.game_id for item in stored] == ["seed-1", "seed-2"]
    assert repository.get_embedding("seed-2") is not None
