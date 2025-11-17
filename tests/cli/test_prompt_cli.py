from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from game_recommendation.cli.app import app
from game_recommendation.cli.commands import prompt
from game_recommendation.core.ingest.builder import GameBuilderError
from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.infra.igdb import IGDBGameDTO
from game_recommendation.shared.exceptions import Result


class StubBuilder:
    def __init__(self, payload: EmbeddedGamePayload) -> None:
        self._payload = payload
        self.calls: list[int] = []

    def build(self, igdb_id: int, *, generate_embedding: bool = True) -> Result:
        self.calls.append(igdb_id)
        return Result.ok(self._payload)


class FailingBuilder(StubBuilder):
    def build(self, igdb_id: int, *, generate_embedding: bool = True) -> Result:
        self.calls.append(igdb_id)
        return Result.err(GameBuilderError("build failed"))


class StubFavoritesLoader:
    def __init__(self, payloads: tuple[EmbeddedGamePayload, ...]) -> None:
        self._payloads = payloads
        self.calls = 0

    def load(self) -> list[EmbeddedGamePayload]:
        self.calls += 1
        return list(self._payloads)


def _payload(
    igdb_id: int,
    *,
    title: str,
    tag_id: int,
    embedding_base: float,
    favorite: bool = True,
) -> EmbeddedGamePayload:
    game = IGDBGameDTO(id=igdb_id, name=title, slug=f"game-{igdb_id}", tags=(tag_id,))
    embedding = IngestedEmbedding(
        title_embedding=(embedding_base, embedding_base * 2),
        description_embedding=(embedding_base * 3, embedding_base * 4),
        model="test-model",
    )
    return EmbeddedGamePayload(
        igdb_game=game,
        description=f"description {igdb_id}",
        tags=(
            GameTagPayload(
                slug=f"tag-{tag_id}", label=f"Tag {tag_id}", tag_class="genre", igdb_id=tag_id
            ),
        ),
        keywords=(),
        embedding=embedding,
        favorite=favorite,
        favorite_notes=None,
    )


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_generate_outputs_prompt_and_file(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _payload(10, title="Target Game", tag_id=50, embedding_base=0.5, favorite=False)
    favorites = (
        _payload(11, title="Similar A", tag_id=50, embedding_base=0.6),
        _payload(12, title="Similar B", tag_id=99, embedding_base=0.1),
    )

    builder = StubBuilder(target)
    loader = StubFavoritesLoader(favorites)
    context = prompt.PromptContext(
        builder=builder,
        favorites_loader=loader,
        settings=None,  # type: ignore[arg-type]
    )

    output_path = tmp_path / "prompt.txt"

    monkeypatch.setattr(prompt, "_prepare_context", lambda *_args, **_kwargs: context)

    result = runner.invoke(
        app,
        [
            "prompt",
            "generate",
            "--igdb-id",
            "10",
            "--output-file",
            str(output_path),
            "--limit",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "Target Game" in result.stdout
    assert "Similar A" in result.stdout
    assert builder.calls == [10]
    assert loader.calls == 1
    assert output_path.read_text(encoding="utf-8").strip() == result.stdout.strip()


def test_generate_handles_builder_error(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = FailingBuilder(
        _payload(20, title="Unused", tag_id=1, embedding_base=0.5, favorite=False)
    )
    loader = StubFavoritesLoader(tuple())
    context = prompt.PromptContext(
        builder=builder,
        favorites_loader=loader,
        settings=None,  # type: ignore[arg-type]
    )

    monkeypatch.setattr(prompt, "_prepare_context", lambda *_args, **_kwargs: context)
    result = runner.invoke(app, ["prompt", "generate", "--igdb-id", "20"])

    assert result.exit_code == 1
    assert "取得に失敗" in result.stdout
    assert builder.calls == [20]
