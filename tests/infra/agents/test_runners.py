"""コーディングエージェント実行ラッパーのテスト。"""

from __future__ import annotations

import pytest

from game_recommendation.infra.agents.base import (
    AgentResponse,
    AgentRunnerError,
    CommandResult,
)
from game_recommendation.infra.agents.claude_code import ClaudeCodeConfig, ClaudeCodeRunner
from game_recommendation.infra.agents.codex import CodexCliConfig, CodexCliRunner


class _FakeCommandRunner:
    def __init__(self, responses: list[CommandResult | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def run(
        self,
        command: tuple[str, ...] | list[str],
    ) -> CommandResult:
        self.calls.append((tuple(command), ""))
        if not self.responses:
            raise RuntimeError("No more responses configured")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _result(
    command: list[str], *, exit_code: int = 0, stdout: str = "", stderr: str = ""
) -> CommandResult:
    return CommandResult(
        command=tuple(command),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


def test_codex_runner_success() -> None:
    prompt = "print('hi')"
    expected_command = ("codex", "exec", prompt, "--json")
    runner = CodexCliRunner(
        CodexCliConfig(),
        command_runner=_FakeCommandRunner(
            [
                _result(
                    list(expected_command),
                    stdout=(
                        '{"type": "item.completed", "item": '
                        '{"type": "agent_message", "text": "ok"}}'
                    ),
                )
            ]
        ),
    )

    result = runner.run(prompt)

    assert isinstance(result, AgentResponse)
    assert result.text == "ok"
    assert result.raw_output.strip().startswith("{")


def test_codex_runner_raises_when_message_missing() -> None:
    prompt = "retry"
    expected_command = ("codex", "exec", prompt, "--json")
    runner = CodexCliRunner(
        CodexCliConfig(),
        command_runner=_FakeCommandRunner(
            [_result(list(expected_command), stdout='{"type": "thread.started"}')]
        ),
    )

    with pytest.raises(AgentRunnerError):
        runner.run(prompt)


def test_claude_runner_success() -> None:
    prompt = "hello"
    expected_command = ("claude", "-p", prompt, "--output-format", "json")
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(),
        command_runner=_FakeCommandRunner(
            [
                _result(
                    list(expected_command),
                    stdout='{ "result": "Hello!" }',
                )
            ]
        ),
    )

    result = runner.run(prompt)

    assert result.text == "Hello!"
    assert "Hello" in result.raw_output


def test_claude_runner_error_on_exit_code() -> None:
    prompt = "ng"
    expected_command = ("claude", "-p", prompt, "--output-format", "json")
    runner = ClaudeCodeRunner(
        ClaudeCodeConfig(),
        command_runner=_FakeCommandRunner(
            [_result(list(expected_command), exit_code=1, stderr="boom")]
        ),
    )

    with pytest.raises(AgentRunnerError):
        runner.run(prompt)
