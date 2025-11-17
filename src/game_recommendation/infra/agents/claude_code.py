"""Claude Code 向けクライアント（最小実装）。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .base import (
    AgentResponse,
    AgentRunnerError,
    CodingAgentRunnerProtocol,
    CommandRunner,
    CommandRunnerProtocol,
    ensure_json_stdout,
    ensure_success,
)


@dataclass(slots=True)
class ClaudeCodeConfig:
    """Claude Code の CLI 実行設定。"""

    cli_path: str = "claude"
    extra_args: tuple[str, ...] = ()


class ClaudeCodeRunner(CodingAgentRunnerProtocol):
    """Claude Code を CLI で呼び出すランナー。"""

    name = "claude-code"

    def __init__(
        self, config: ClaudeCodeConfig, *, command_runner: CommandRunnerProtocol | None = None
    ):
        self.config = config
        self.command_runner = command_runner or CommandRunner()

    def run(self, prompt: str) -> AgentResponse:
        command = [
            self.config.cli_path,
            "-p",
            prompt,
            "--output-format",
            "json",
            *self.config.extra_args,
        ]
        result = self.command_runner.run(command)
        ensure_success(result)
        stdout = ensure_json_stdout(result)
        message = self._extract_result(stdout)
        return AgentResponse(text=message, raw_output=stdout)

    @staticmethod
    def _extract_result(stdout: str) -> str:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - 想定外フォーマット
            raise AgentRunnerError("Claude Code の出力が JSON ではありません") from exc

        if "result" not in payload:
            msg = "Claude Code の出力に result が含まれていません"
            raise AgentRunnerError(msg)
        return str(payload["result"])


__all__ = ["ClaudeCodeConfig", "ClaudeCodeRunner"]
