from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from game_recommendation.cli.app import app
from game_recommendation.infra.igdb import (
    IGDBGameDTO,
    IGDBGameResponse,
    IGDBQuery,
    IGDBRateLimitError,
    IGDBRequestError,
    IGDBResponseFormat,
)


class StubIGDBClient:
    def __init__(self, response: tuple[IGDBGameDTO, ...]):
        self._response = response
        self.calls: list[tuple[IGDBQuery, IGDBResponseFormat]] = []

    def fetch_games(
        self,
        query: IGDBQuery,
        response_format: IGDBResponseFormat = IGDBResponseFormat.JSON,
    ) -> IGDBGameResponse:
        self.calls.append((query, response_format))
        return IGDBGameResponse(items=self._response, raw=b"{}", format=response_format)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def sample_game() -> IGDBGameDTO:
    return IGDBGameDTO(
        id=1,
        name="Halo Infinite",
        slug="halo-infinite",
        summary="Sample summary",
        first_release_date=datetime(2021, 12, 8, tzinfo=UTC),
        cover_image_id="cover123",
        platforms=(48,),
        category=0,
        tags=(10, 11),
    )


@pytest.fixture()
def stub_client(monkeypatch: pytest.MonkeyPatch, sample_game: IGDBGameDTO) -> StubIGDBClient:
    client = StubIGDBClient((sample_game,))
    monkeypatch.setattr(
        "game_recommendation.cli.commands.igdb.build_igdb_client", lambda **_kwargs: client
    )
    return client


def test_search_outputs_table(runner: CliRunner, stub_client: StubIGDBClient) -> None:
    result = runner.invoke(
        app,
        ["igdb", "search", "--title", "Halo", "--limit", "5", "--offset", "1"],
    )

    assert result.exit_code == 0
    assert any("Halo" in line for line in result.stdout.splitlines())
    query, response_format = stub_client.calls[0]
    assert query.search_term == "Halo"
    assert query.where_clauses == ()
    assert query.sort_clause is None
    assert query.limit_value >= 5
    assert query.offset_value == 1
    assert response_format is IGDBResponseFormat.JSON


def test_search_outputs_json(runner: CliRunner, stub_client: StubIGDBClient) -> None:
    result = runner.invoke(app, ["igdb", "search", "--title", "Halo", "--output", "json"])

    assert result.exit_code == 0
    json_start = result.stdout.find("\n[")
    assert json_start != -1
    payload = json.loads(result.stdout[json_start + 1 :])
    assert payload[0]["name"] == "Halo Infinite"
    assert payload[0]["platforms"] == [48]


def test_search_exact_match_uses_where_clause(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, sample_game: IGDBGameDTO
) -> None:
    client = StubIGDBClient((sample_game,))
    monkeypatch.setattr(
        "game_recommendation.cli.commands.igdb.build_igdb_client", lambda **_kwargs: client
    )

    result = runner.invoke(app, ["igdb", "search", "--title", "Halo", "--match", "exact"])

    assert result.exit_code == 0
    query, _ = client.calls[0]
    assert query.search_term is None
    assert query.where_clauses == ('name = "Halo"',)
    assert query.sort_clause == ("first_release_date", "desc")


def test_search_handles_request_error(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def fetch_games(self, *_args, **_kwargs):
            raise IGDBRequestError("failure")

    monkeypatch.setattr(
        "game_recommendation.cli.commands.igdb.build_igdb_client", lambda **_kwargs: FailingClient()
    )

    result = runner.invoke(app, ["igdb", "search", "--title", "Halo"])

    assert result.exit_code == 1
    assert "IGDB 検索に失敗しました" in result.stdout


def test_search_handles_rate_limit(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitedClient:
        def fetch_games(self, *_args, **_kwargs):
            raise IGDBRateLimitError("rate limit")

    monkeypatch.setattr(
        "game_recommendation.cli.commands.igdb.build_igdb_client",
        lambda **_kwargs: RateLimitedClient(),
    )

    result = runner.invoke(app, ["igdb", "search", "--title", "Halo"])

    assert result.exit_code == 2
    assert "レート制限" in result.stdout
