"""Codex CLI 向けクライアント。"""

from __future__ import annotations

import json
from collections.abc import Sequence
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
class CodexCliConfig:
    """Codex CLI 実行に必要な設定。"""

    cli_path: str = "codex"
    extra_args: tuple[str, ...] = ()


class CodexCliRunner(CodingAgentRunnerProtocol):
    """Codex CLI をサブプロセスとして呼び出すランナー。"""

    name = "codex-cli"

    def __init__(
        self, config: CodexCliConfig, *, command_runner: CommandRunnerProtocol | None = None
    ):
        self.config = config
        self.command_runner = command_runner or CommandRunner()

    def run(self, prompt: str) -> AgentResponse:
        command: Sequence[str] = [
            self.config.cli_path,
            "exec",
            prompt,
            "--json",
            *self.config.extra_args,
        ]
        result = self.command_runner.run(command)
        ensure_success(result)
        stdout = ensure_json_stdout(result)
        message = self._extract_agent_message(stdout)
        return AgentResponse(text=message, raw_output=stdout)

    @staticmethod
    def _extract_agent_message(stdout: str) -> str:
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "item.completed":
                item = payload.get("item") or {}
                if item.get("type") == "agent_message" and "text" in item:
                    return str(item["text"])
        raise AgentRunnerError("Codex から agent_message を取得できませんでした")


__all__ = ["CodexCliConfig", "CodexCliRunner"]
