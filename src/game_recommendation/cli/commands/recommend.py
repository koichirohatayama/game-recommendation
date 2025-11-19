from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Annotated

import typer
from structlog.stdlib import BoundLogger

from game_recommendation.cli.commands import prompt
from game_recommendation.core.prompting.builder import RecommendationPromptResult
from game_recommendation.infra.agents.base import AgentRunnerError, CodingAgentRunnerProtocol
from game_recommendation.infra.agents.claude_code import ClaudeCodeConfig, ClaudeCodeRunner
from game_recommendation.infra.agents.codex import CodexCliConfig, CodexCliRunner
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger


class AgentChoice(StrEnum):
    CODEX_CLI = "codex-cli"
    CLAUDE_CODE = "claude-code"


DEFAULT_SIMILAR_LIMIT = 3

app = typer.Typer(help="IGDB ID から推薦判定を実行するコマンド")


def _prepare_context(settings: AppSettings, logger: BoundLogger) -> prompt.PromptContext:
    return prompt._prepare_context(settings=settings, logger=logger)


def _build_prompt(
    *, context: prompt.PromptContext, igdb_id: int, logger: BoundLogger, top_n: int
) -> RecommendationPromptResult:
    return prompt._generate_prompt(context=context, igdb_id=igdb_id, top_n=top_n, logger=logger)


def _create_agent_runner(agent: AgentChoice) -> CodingAgentRunnerProtocol:
    if agent is AgentChoice.CODEX_CLI:
        return CodexCliRunner(CodexCliConfig())
    if agent is AgentChoice.CLAUDE_CODE:
        return ClaudeCodeRunner(ClaudeCodeConfig())
    msg = f"エージェント {agent} はサポートされていません"
    raise AgentRunnerError(msg)


_JSON_DECODER = json.JSONDecoder()
_JSON_OBJECT_PATTERN = re.compile(r"\{")


def _iter_json_candidates(text: str) -> list[object]:
    """テキスト内のJSONオブジェクト候補を順番に抽出する。"""

    def _decode_candidate(candidate: str) -> object | None:
        snippet = candidate.lstrip()
        if not snippet.startswith("{"):
            return None
        try:
            payload, _ = _JSON_DECODER.raw_decode(snippet)
        except json.JSONDecodeError:
            return None
        return payload

    candidates: list[object] = []
    direct = _decode_candidate(text)
    if direct is not None:
        candidates.append(direct)

    starts = {match.start() for match in _JSON_OBJECT_PATTERN.finditer(text)}
    for start in sorted(starts):
        if start == 0:
            continue
        decoded = _decode_candidate(text[start:])
        if decoded is not None:
            candidates.append(decoded)
    return candidates


def _parse_agent_response(text: str) -> dict[str, object]:
    for candidate in _iter_json_candidates(text):
        if not isinstance(candidate, dict):
            continue
        if "recommend" in candidate and "reason" in candidate:
            return candidate

    msg = "エージェントの出力がJSONではありません"
    raise AgentRunnerError(msg)


@app.command()
def run(
    igdb_id: Annotated[int, typer.Option("--igdb-id", "-i", help="判定対象のIGDB ID")],
    agent: Annotated[
        AgentChoice,
        typer.Option(
            "--agent",
            "-a",
            case_sensitive=False,
            help="実行するコーディングエージェント (codex-cli/claude-code)",
        ),
    ] = AgentChoice.CODEX_CLI,
) -> None:
    """IGDB ID からプロンプトを生成し、コーディングエージェントで判定する。"""

    logger = get_logger("cli.recommend.run", igdb_id=igdb_id, agent=str(agent))
    try:
        settings = get_settings()
        context = _prepare_context(settings=settings, logger=logger)
    except BaseAppError as exc:
        logger.error("recommend_context_failed", error=str(exc))
        typer.echo(f"設定の読み込みに失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    prompt_result = _build_prompt(
        context=context, igdb_id=igdb_id, logger=logger, top_n=DEFAULT_SIMILAR_LIMIT
    )

    runner = _create_agent_runner(agent)
    try:
        response = runner.run(prompt_result.prompt)
    except AgentRunnerError as exc:
        logger.error("recommend_agent_run_failed", error=str(exc))
        typer.echo(f"エージェントの実行に失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    try:
        payload = _parse_agent_response(response.text)
    except AgentRunnerError as exc:
        logger.error(
            "recommend_agent_output_invalid", error=str(exc), raw_output=response.raw_output
        )
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    logger.info("recommend_completed", agent=str(agent))
    typer.echo(json.dumps(payload, ensure_ascii=False))


__all__ = ["app"]
