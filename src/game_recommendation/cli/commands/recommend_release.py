from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

import typer
from structlog.stdlib import BoundLogger

from game_recommendation.cli.commands import prompt as prompt_cli
from game_recommendation.cli.commands import recommend as recommend_cli
from game_recommendation.infra.agents.base import AgentRunnerError
from game_recommendation.infra.discord.client import (
    DiscordWebhookClient,
    DiscordWebhookError,
    DiscordWebhookRequest,
)
from game_recommendation.infra.discord.templates import truncate_text
from game_recommendation.infra.igdb import (
    IGDBGameDTO,
    IGDBQuery,
    IGDBQueryBuilder,
    IGDBRateLimitError,
    IGDBRequestError,
    IGDBResponseFormat,
)
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger

app = typer.Typer(
    help="リリース日から推薦判定を実行するコマンド",
    invoke_without_command=True,
    no_args_is_help=True,
)


def _prepare_context(settings: AppSettings, logger: BoundLogger) -> prompt_cli.PromptContext:
    return prompt_cli._prepare_context(settings=settings, logger=logger)


def _parse_release_date(raw: str | None) -> date:
    if raw is None:
        return date.today()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        msg = "リリース日は YYYY-MM-DD 形式で指定してください"
        raise typer.BadParameter(msg) from exc


def _build_release_query(game_ids: tuple[int, ...]) -> IGDBQuery:
    ids = ",".join(str(game_id) for game_id in game_ids)
    return (
        IGDBQueryBuilder()
        .select("id", "name", "slug", "first_release_date", "category")
        .where(f"id = ({ids})")
        .limit(len(game_ids))
        .build()
    )


def _fetch_release_game_ids(*, client, release_date: date, logger: BoundLogger) -> tuple[int, ...]:
    start = datetime.combine(release_date, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    query = (
        IGDBQueryBuilder()
        .select("game", "date")
        .where(f"date >= {int(start.timestamp())}")
        .where(f"date < {int(end.timestamp())}")
        .build()
    )

    try:
        payload = client._perform_request(  # noqa: SLF001 - IGDBClientの内部実装を再利用
            endpoint="release_dates",
            query=query,
            response_format=IGDBResponseFormat.JSON,
        )
    except IGDBRateLimitError as exc:
        logger.warning("recommend_release_rate_limited", error=str(exc))
        typer.echo("IGDB API のレート制限に到達しました。時間をおいて再実行してください。")
        raise typer.Exit(code=2) from exc
    except IGDBRequestError as exc:
        logger.error("recommend_release_fetch_failed", error=str(exc))
        typer.echo(f"リリース日 {release_date.isoformat()} の取得に失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error("recommend_release_parse_failed", error=str(exc))
        typer.echo("IGDB API レスポンスの解析に失敗しました")
        raise typer.Exit(code=1) from exc

    ids: set[int] = set()
    for item in parsed if isinstance(parsed, list) else []:
        game_id = item.get("game") if isinstance(item, dict) else None
        if isinstance(game_id, int):
            ids.add(game_id)
    return tuple(sorted(ids))


def _fetch_release_games(
    *, client, release_date: date, logger: BoundLogger
) -> tuple[IGDBGameDTO, ...]:
    game_ids = _fetch_release_game_ids(client=client, release_date=release_date, logger=logger)
    if not game_ids:
        return ()

    query = _build_release_query(game_ids)
    response = client.fetch_games(query, response_format=IGDBResponseFormat.JSON)
    return response.items


def _build_prompt(*, context, igdb_id: int, logger: BoundLogger):
    return recommend_cli._build_prompt(
        context=context,
        igdb_id=igdb_id,
        logger=logger,
        top_n=recommend_cli.DEFAULT_SIMILAR_LIMIT,
    )


def _create_agent_runner(agent: recommend_cli.AgentChoice):
    return recommend_cli._create_agent_runner(agent)


def _parse_agent_response(text: str):
    return recommend_cli._parse_agent_response(text)


def _format_discord_message(*, game: IGDBGameDTO, reason: str, release_date: date) -> str:
    release_text = (
        game.first_release_date.date().isoformat()
        if game.first_release_date
        else release_date.isoformat()
    )
    lines = [
        "🎉 新着ゲーム推薦",
        f"タイトル: {game.name} (ID: {game.id})",
        f"リリース日: {release_text}",
    ]
    if game.slug:
        lines.append(f"Slug: {game.slug}")
    if reason:
        lines.append(f"推薦理由: {truncate_text(reason, 400)}")
    else:
        lines.append("推薦理由: (未提供)")

    return "\n".join(lines)


def _build_discord_embed(
    *, game: IGDBGameDTO, reason: str, release_date: date
) -> dict[str, object]:
    description = truncate_text(reason or "推薦理由なし", 1000)
    release_text = (
        game.first_release_date.date().isoformat()
        if game.first_release_date
        else release_date.isoformat()
    )

    fields = [
        {"name": "リリース日", "value": release_text, "inline": True},
    ]
    if game.slug:
        fields.append({"name": "Slug", "value": game.slug, "inline": True})

    return {
        "title": game.name,
        "description": description,
        "color": 0x5865F2,  # Discord blurple
        "fields": fields,
        "footer": {"text": f"IGDB ID: {game.id}"},
    }


def _notify_discord(
    *,
    game: IGDBGameDTO,
    reason: str,
    settings: AppSettings,
    release_date: date,
    logger: BoundLogger,
) -> None:
    client = DiscordWebhookClient(
        webhook_url=str(settings.discord.webhook_url),
        default_username=settings.discord.webhook_username,
        logger=logger,
    )
    embed = _build_discord_embed(game=game, reason=reason, release_date=release_date)
    client.send(
        DiscordWebhookRequest(
            content="",
            username=settings.discord.webhook_username,
            embeds=[embed],
        )
    )


@app.callback()
def run(
    release_date: Annotated[
        str | None,
        typer.Option(
            "--release-date",
            "-d",
            help="YYYY-MM-DD 形式のリリース日。省略時は当日。",
        ),
    ] = None,
    agent: Annotated[
        recommend_cli.AgentChoice,
        typer.Option(
            "--agent",
            "-a",
            case_sensitive=False,
            help="実行するコーディングエージェント (codex-cli/claude-code)",
        ),
    ] = recommend_cli.AgentChoice.CODEX_CLI,
) -> None:
    """リリース日を指定して新着ゲームの推薦判定を実行する。"""

    target_date = _parse_release_date(release_date)
    logger = get_logger(
        "cli.recommend_release.run",
        release_date=target_date.isoformat(),
        agent=str(agent),
    )

    try:
        settings = get_settings()
        context = _prepare_context(settings=settings, logger=logger)
    except BaseAppError as exc:
        logger.error("recommend_release_context_failed", error=str(exc))
        typer.echo(f"設定の読み込みに失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    games = _fetch_release_games(
        client=context.builder.igdb_client, release_date=target_date, logger=logger
    )

    total = len(games)
    typer.echo(f"{target_date.isoformat()} のリリース候補: {total} 件")
    if not games:
        return

    runner = _create_agent_runner(agent)
    errors = False
    recommended = 0

    for index, game in enumerate(games, start=1):
        typer.echo(f"[{index}/{total}] {game.name} (ID: {game.id}) を評価しています")
        prompt_result = _build_prompt(context=context, igdb_id=game.id, logger=logger)

        try:
            response = runner.run(prompt_result.prompt)
        except AgentRunnerError as exc:
            logger.error("recommend_release_agent_failed", igdb_id=game.id, error=str(exc))
            typer.echo(f"エージェントの実行に失敗しました: {exc}")
            errors = True
            continue

        try:
            payload = _parse_agent_response(response.text)
        except AgentRunnerError as exc:
            logger.error(
                "recommend_release_agent_output_invalid",
                igdb_id=game.id,
                raw_output=response.raw_output,
                error=str(exc),
            )
            typer.echo(f"エージェント出力が不正です: {exc}")
            errors = True
            continue

        recommend_flag = bool(payload.get("recommend"))
        reason = str(payload.get("reason", ""))

        if recommend_flag:
            recommended += 1
            typer.echo("推薦: Discord へ通知します")
            try:
                _notify_discord(
                    game=game,
                    reason=reason,
                    settings=settings,
                    release_date=target_date,
                    logger=logger,
                )
            except DiscordWebhookError as exc:
                logger.error(
                    "recommend_release_discord_failed",
                    igdb_id=game.id,
                    error=str(exc),
                )
                typer.echo(f"Discord通知に失敗しました: {exc}")
                errors = True
            else:
                typer.echo("Discord通知を送信しました")
        else:
            typer.echo("推薦: 見送り")

    logger.info(
        "recommend_release_completed",
        processed=total,
        recommended=recommended,
        errors=errors,
    )
    if errors:
        raise typer.Exit(code=1)


__all__ = ["app", "run"]
