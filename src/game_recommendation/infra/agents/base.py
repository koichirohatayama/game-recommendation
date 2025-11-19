"""コーディングエージェント実行の最小抽象化。"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.types import DTO


class AgentRunnerError(BaseAppError):
    """エージェント実行時の例外。"""

    default_message = "Coding agent execution failed"


@dataclass(slots=True)
class AgentResponse(DTO):
    """シンプルなエージェント応答。"""

    text: str
    raw_output: str


@dataclass(slots=True)
class CommandResult(DTO):
    """サブプロセス実行結果。"""

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str


@runtime_checkable
class CommandRunnerProtocol(Protocol):
    """subprocess 実行責務。"""

    def run(  # pragma: no cover - Protocol
        self, command: Sequence[str]
    ) -> CommandResult: ...


@dataclass(slots=True)
class CommandRunner(CommandRunnerProtocol):
    """subprocess.run を包む薄いラッパー。"""

    def run(self, command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
        )
        return CommandResult(
            command=tuple(command),
            exit_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


@runtime_checkable
class CodingAgentRunnerProtocol(Protocol):
    """コーディングエージェントの共通契約。"""

    name: str

    def run(self, prompt: str) -> AgentResponse:  # pragma: no cover - Protocol
        ...


def ensure_success(result: CommandResult) -> None:
    """非ゼロ終了時に例外化する。"""

    if result.exit_code != 0:
        msg = f"エージェント実行に失敗しました (exit {result.exit_code}): {result.stderr.strip()}"
        raise AgentRunnerError(msg)


def ensure_json_stdout(result: CommandResult) -> str:
    if not result.stdout.strip():
        msg = "エージェントからの標準出力が空です"
        raise AgentRunnerError(msg)
    return result.stdout


__all__ = [
    "AgentResponse",
    "AgentRunnerError",
    "CodingAgentRunnerProtocol",
    "CommandResult",
    "CommandRunner",
    "CommandRunnerProtocol",
    "ensure_json_stdout",
    "ensure_success",
]
