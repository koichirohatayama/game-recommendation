from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from game_recommendation.cli.app import app
from game_recommendation.cli.commands import recommend
from game_recommendation.core.prompting.builder import (
    RecommendationPromptResult,
    RecommendationPromptSections,
)
from game_recommendation.infra.agents.base import AgentResponse


class DummyLogger:
    def __init__(self) -> None:
        self.errors: list[dict[str, object]] = []

    def info(self, *_args, **_kwargs) -> None:  # pragma: no cover - ログ検証は不要
        return None

    def error(self, *_args, **kwargs) -> None:
        self.errors.append(kwargs)


class StubRunner:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def run(self, prompt_text: str) -> AgentResponse:
        self.prompts.append(prompt_text)
        return AgentResponse(text=self.response, raw_output=self.response)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _prompt_result(prompt_text: str) -> RecommendationPromptResult:
    sections = RecommendationPromptSections(
        target_overview="target",
        tag_similar=tuple(),
        title_similar=tuple(),
        storyline_similar=tuple(),
        summary_similar=tuple(),
    )
    return RecommendationPromptResult(
        prompt=prompt_text,
        template_name="template.txt",
        sections=sections,
    )


def test_run_executes_agent_and_outputs_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = object()
    prompt_result = _prompt_result("PROMPT")
    calls: dict[str, object] = {}

    monkeypatch.setattr(recommend, "get_settings", lambda: object())
    monkeypatch.setattr(recommend, "get_logger", lambda *_args, **_kwargs: DummyLogger())
    monkeypatch.setattr(recommend, "_prepare_context", lambda settings, logger: context)

    def fake_build_prompt(*, context: object, igdb_id: int, logger: object, top_n: int):
        calls["build_args"] = (context, igdb_id, top_n)
        return prompt_result

    monkeypatch.setattr(recommend, "_build_prompt", fake_build_prompt)

    agent_runner = StubRunner('{"recommend": true, "reason": "OK"}')
    monkeypatch.setattr(recommend, "_create_agent_runner", lambda agent: agent_runner)

    result = runner.invoke(
        app,
        ["recommend", "run", "--igdb-id", "101", "--agent", "codex-cli"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"recommend": True, "reason": "OK"}
    assert agent_runner.prompts == [prompt_result.prompt]
    assert calls["build_args"] == (context, 101, recommend.DEFAULT_SIMILAR_LIMIT)


def test_run_handles_invalid_agent_output(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = DummyLogger()
    monkeypatch.setattr(recommend, "get_settings", lambda: object())
    monkeypatch.setattr(recommend, "get_logger", lambda *_args, **_kwargs: logger)
    monkeypatch.setattr(recommend, "_prepare_context", lambda settings, logger: object())
    monkeypatch.setattr(recommend, "_build_prompt", lambda **_kwargs: _prompt_result("PROMPT"))

    agent_runner = StubRunner("not-json")
    monkeypatch.setattr(recommend, "_create_agent_runner", lambda agent: agent_runner)

    result = runner.invoke(
        app,
        ["recommend", "run", "--igdb-id", "202", "--agent", "claude-code"],
    )

    assert result.exit_code == 1
    assert "JSONではありません" in result.stdout
    assert logger.errors[-1].get("raw_output") == "not-json"
