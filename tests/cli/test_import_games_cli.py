from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from game_recommendation.cli.app import app
from game_recommendation.cli.commands import import_games
from game_recommendation.core.ingest.builder import GameBuilderError
from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.infra.db.models import (
    Base,
    GameEmbedding,
    GameTag,
    GameTagLink,
    IgdbGame,
    UserFavoriteGame,
)
from game_recommendation.infra.db.session import DatabaseSessionManager
from game_recommendation.infra.igdb import IGDBGameDTO
from game_recommendation.shared.config import (
    AppSettings,
    DiscordSettings,
    GeminiSettings,
    IGDBSettings,
    StorageSettings,
)
from game_recommendation.shared.exceptions import Result


class StubBuilder:
    def __init__(self, payloads: dict[int, EmbeddedGamePayload]) -> None:
        self._payloads = payloads
        self.calls: list[int] = []

    def build(self, igdb_id: int, *, generate_embedding: bool = True) -> Result:
        self.calls.append(igdb_id)
        if igdb_id not in self._payloads:
            return Result.err(GameBuilderError(f"missing {igdb_id}"))
        return Result.ok(self._payloads[igdb_id])


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        igdb=IGDBSettings(
            client_id="client-id",
            client_secret="secret",
            token_url="https://example.com/token",
        ),
        discord=DiscordSettings(webhook_url="https://example.com/webhook", webhook_username="bot"),
        gemini=GeminiSettings(api_key="dummy-key", model="test-model"),
        storage=StorageSettings(sqlite_path=tmp_path / "games.db"),
    )


def _payload(igdb_id: int, *, tag_slug: str, tag_igdb_id: int | None = None) -> EmbeddedGamePayload:
    game = IGDBGameDTO(id=igdb_id, name=f"Game {igdb_id}", slug=f"game-{igdb_id}", tags=(1,))
    embedding = IngestedEmbedding(
        title_embedding=(0.1, 0.2),
        description_embedding=(0.3, 0.4),
        model="test-model",
    )
    effective_tag_id = tag_igdb_id if tag_igdb_id is not None else igdb_id
    return EmbeddedGamePayload(
        igdb_game=game,
        description="sample",
        tags=(
            GameTagPayload(
                slug=tag_slug,
                label=tag_slug.title(),
                tag_class="genre",
                igdb_id=effective_tag_id,
            ),
        ),
        embedding=embedding,
        favorite=True,
        favorite_notes="fav",
    )


def _prepare_stub_context(
    *,
    settings: AppSettings,
    builder: StubBuilder,
    db_required: bool,
) -> import_games.ImportContext:
    db_manager = None
    if db_required:
        db_manager = DatabaseSessionManager(db_path=settings.storage.sqlite_path, settings=settings)
        Base.metadata.create_all(db_manager.engine)
    return import_games.ImportContext(builder=builder, db_manager=db_manager, settings=settings)


def test_import_games_inserts_all_tables(
    runner: CliRunner, settings: AppSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {
        1: _payload(1, tag_slug="action"),
        2: _payload(2, tag_slug="rpg"),
    }
    builder = StubBuilder(payloads)
    context = _prepare_stub_context(settings=settings, builder=builder, db_required=True)

    monkeypatch.setattr(import_games, "get_settings", lambda: settings)
    monkeypatch.setattr(
        import_games,
        "_prepare_context",
        lambda dry_run, settings, logger: context,
    )

    result = runner.invoke(app, ["import", "--igdb-ids", "1,2", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    statuses = {item["igdb_id"]: item["status"] for item in payload}
    assert statuses == {1: "imported", 2: "imported"}

    with context.db_manager.session() as session:  # type: ignore[union-attr]
        games = session.scalars(select(IgdbGame)).all()
        embeddings = session.scalars(select(GameEmbedding)).all()
        tags = session.scalars(select(GameTag)).all()
        tag_links = session.scalars(select(GameTagLink)).all()
        favorites = session.scalars(select(UserFavoriteGame)).all()

    assert len(games) == 2
    assert len(embeddings) == 2
    assert len(tags) == 2
    assert len(tag_links) == 2
    assert len(favorites) == 2


def test_import_games_supports_dry_run(
    runner: CliRunner, settings: AppSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = StubBuilder({3: _payload(3, tag_slug="puzzle")})
    context = _prepare_stub_context(settings=settings, builder=builder, db_required=False)

    monkeypatch.setattr(import_games, "get_settings", lambda: settings)
    monkeypatch.setattr(
        import_games,
        "_prepare_context",
        lambda dry_run, settings, logger: context,
    )

    result = runner.invoke(
        app,
        ["import", "--igdb-ids", "3", "--output", "json", "--dry-run"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["status"] == "dry-run"
    assert not settings.storage.sqlite_path.exists()


def test_import_games_reports_failed_ids(
    runner: CliRunner, settings: AppSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = StubBuilder({4: _payload(4, tag_slug="sim")})
    context = _prepare_stub_context(settings=settings, builder=builder, db_required=True)

    monkeypatch.setattr(import_games, "get_settings", lambda: settings)
    monkeypatch.setattr(
        import_games,
        "_prepare_context",
        lambda dry_run, settings, logger: context,
    )

    result = runner.invoke(app, ["import", "--igdb-ids", "5,4", "--output", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    statuses = {item["igdb_id"]: item["status"] for item in payload}
    assert statuses[5] == "failed"
    assert statuses[4] == "imported"
