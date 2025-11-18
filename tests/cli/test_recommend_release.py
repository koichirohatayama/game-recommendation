from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from game_recommendation.cli.app import app
from game_recommendation.cli.commands import recommend_release
from game_recommendation.infra.agents.base import AgentResponse
from game_recommendation.infra.discord.client import DiscordWebhookError
from game_recommendation.infra.igdb import IGDBGameDTO


class DummyLogger:
    def __init__(self) -> None:
        self.errors: list[dict[str, object]] = []
        self.warnings: list[dict[str, object]] = []

    def info(self, *_args, **_kwargs) -> None:  # pragma: no cover - ログ検証は不要
        return None

    def warning(self, *_args, **kwargs) -> None:
        self.warnings.append(kwargs)

    def error(self, *_args, **kwargs) -> None:
        self.errors.append(kwargs)


class StubRunner:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def run(self, prompt_text: str) -> AgentResponse:
        self.prompts.append(prompt_text)
        text = self._responses.pop(0)
        return AgentResponse(text=text, raw_output=text)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_run_notifies_recommended_games(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    games = (
        IGDBGameDTO(id=1, name="First"),
        IGDBGameDTO(id=2, name="Second"),
    )
    logger = DummyLogger()
    context = SimpleNamespace(builder=SimpleNamespace(igdb_client=object()))
    settings = SimpleNamespace(
        discord=SimpleNamespace(
            webhook_url="http://example.com",
            webhook_username="bot",
        )
    )

    monkeypatch.setattr(recommend_release, "get_settings", lambda: settings)
    monkeypatch.setattr(recommend_release, "get_logger", lambda *_args, **_kwargs: logger)
    monkeypatch.setattr(recommend_release, "_prepare_context", lambda settings, logger: context)
    monkeypatch.setattr(
        recommend_release,
        "_fetch_release_games",
        lambda *, client, release_date, logger: games,
    )
    monkeypatch.setattr(
        recommend_release,
        "_build_prompt",
        lambda *, context, igdb_id, logger: SimpleNamespace(prompt=f"PROMPT-{igdb_id}"),
    )

    agent_runner = StubRunner(
        ['{"recommend": true, "reason": "OK"}', '{"recommend": false, "reason": "NG"}']
    )
    monkeypatch.setattr(recommend_release, "_create_agent_runner", lambda agent: agent_runner)

    notifications: list[tuple[int, str, date]] = []

    def record_notification(**kwargs) -> None:
        game = kwargs["game"]
        reason = kwargs["reason"]
        release_date = kwargs["release_date"]
        notifications.append((game.id, reason, release_date))

    monkeypatch.setattr(recommend_release, "_notify_discord", record_notification)

    result = runner.invoke(app, ["recommend-release", "--release-date", "2024-01-01"])

    assert result.exit_code == 0
    assert agent_runner.prompts == ["PROMPT-1", "PROMPT-2"]
    assert notifications == [(1, "OK", date(2024, 1, 1))]


def test_run_still_exits_error_when_notification_fails(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    games = (IGDBGameDTO(id=100, name="NotifyFail"),)
    logger = DummyLogger()
    context = SimpleNamespace(builder=SimpleNamespace(igdb_client=object()))
    settings = SimpleNamespace(
        discord=SimpleNamespace(
            webhook_url="http://example.com",
            webhook_username="bot",
        )
    )

    monkeypatch.setattr(recommend_release, "get_settings", lambda: settings)
    monkeypatch.setattr(recommend_release, "get_logger", lambda *_args, **_kwargs: logger)
    monkeypatch.setattr(recommend_release, "_prepare_context", lambda settings, logger: context)
    monkeypatch.setattr(
        recommend_release,
        "_fetch_release_games",
        lambda *, client, release_date, logger: games,
    )
    monkeypatch.setattr(
        recommend_release,
        "_build_prompt",
        lambda *, context, igdb_id, logger: SimpleNamespace(prompt="PROMPT"),
    )

    agent_runner = StubRunner(['{"recommend": true, "reason": "YES"}'])
    monkeypatch.setattr(recommend_release, "_create_agent_runner", lambda agent: agent_runner)

    def raise_notification(**_kwargs) -> None:
        raise DiscordWebhookError("boom")

    monkeypatch.setattr(recommend_release, "_notify_discord", raise_notification)

    result = runner.invoke(app, ["recommend-release", "--release-date", "2024-02-10"])

    assert result.exit_code == 1
    assert "Discord通知に失敗しました" in result.stdout
