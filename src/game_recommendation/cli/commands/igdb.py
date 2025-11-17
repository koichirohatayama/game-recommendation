from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from game_recommendation.infra.igdb import (
    IGDBGameDTO,
    IGDBQuery,
    IGDBQueryBuilder,
    IGDBRateLimitError,
    IGDBRequestError,
    IGDBResponseFormat,
    build_igdb_client,
)
from game_recommendation.shared.logging import get_logger


class TitleMatch(str, Enum):
    """タイトルマッチの方法。"""

    SEARCH = "search"
    CONTAINS = "contains"
    EXACT = "exact"


class OutputFormat(str, Enum):
    """出力形式。"""

    TABLE = "table"
    JSON = "json"


app = typer.Typer(help="IGDB の検索コマンド")


def _escape(term: str) -> str:
    return term.replace('"', '\\"')


def _build_query(title: str, match: TitleMatch, limit: int, offset: int) -> IGDBQuery:
    effective_limit = 50 if match is TitleMatch.SEARCH else limit

    builder = (
        IGDBQueryBuilder()
        .select(
            "id",
            "name",
            "slug",
            "summary",
            "storyline",
            "first_release_date",
            "cover.image_id",
            "platforms",
            "category",
            "tags",
        )
        .limit(effective_limit)
        .offset(offset)
    )

    if match is TitleMatch.SEARCH:
        builder.search(title)
    elif match is TitleMatch.CONTAINS:
        builder.where(f'name ~ *"{_escape(title)}"*')
        builder.sort("first_release_date", "desc")
    elif match is TitleMatch.EXACT:
        builder.where(f'name = "{_escape(title)}"')
        builder.sort("first_release_date", "desc")

    return builder.build()


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.date().isoformat()


def _format_sequence(values: tuple[int, ...]) -> str:
    return ", ".join(str(item) for item in values) if values else "-"


def _game_to_dict(game: IGDBGameDTO) -> dict[str, object]:
    return {
        "id": game.id,
        "name": game.name,
        "slug": game.slug,
        "summary": game.summary,
        "storyline": game.storyline,
        "first_release_date": game.first_release_date.isoformat()
        if game.first_release_date
        else None,
        "cover_image_id": game.cover_image_id,
        "platforms": list(game.platforms),
        "tags": list(game.tags),
    }


def _render_table(items: Iterable[IGDBGameDTO]) -> None:
    console = Console(force_terminal=False, color_system=None)
    table = Table(title="IGDB Title Search")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Slug")
    table.add_column("Release")
    table.add_column("Platforms")
    table.add_column("Tags")
    table.add_column("Cover")

    for game in items:
        table.add_row(
            str(game.id),
            game.name,
            game.slug or "-",
            _format_date(game.first_release_date),
            _format_sequence(game.platforms),
            _format_sequence(game.tags),
            game.cover_image_id or "-",
        )

    console.print(table)


def _render_json(items: Iterable[IGDBGameDTO]) -> None:
    payload = [_game_to_dict(item) for item in items]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def search(  # noqa: PLR0913 - CLI のため引数が多い
    title: Annotated[str, typer.Option("--title", "-t", help="検索するゲームタイトル")] = ...,
    match: Annotated[
        TitleMatch,
        typer.Option(
            "--match",
            "-m",
            case_sensitive=False,
            help="search/contains/exact から指定",
        ),
    ] = TitleMatch.SEARCH,
    limit: Annotated[int, typer.Option("--limit", "-l", min=1, max=500, help="取得する件数")] = 10,
    offset: Annotated[int, typer.Option("--offset", "-o", min=0, help="取得開始位置")] = 0,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-f",
            case_sensitive=False,
            help="出力形式(table/json)",
        ),
    ] = OutputFormat.TABLE,
    response_format: Annotated[
        IGDBResponseFormat,
        typer.Option(
            "--response-format",
            "-r",
            case_sensitive=False,
            help="IGDB API レスポンス形式(JSON/PROTOBUF)",
        ),
    ] = IGDBResponseFormat.JSON,
) -> None:
    """IGDB のタイトル検索を実行する。"""

    logger = get_logger("cli.igdb.search", title=title)
    query = _build_query(title, match, limit, offset)
    client = build_igdb_client(logger=logger)

    try:
        response = client.fetch_games(query, response_format=response_format)
    except IGDBRateLimitError as exc:
        logger.warning("IGDB API rate limited", error=str(exc))
        typer.echo("IGDB API のレート制限に到達しました。時間をおいて再実行してください。")
        raise typer.Exit(code=2) from exc
    except IGDBRequestError as exc:
        logger.error("IGDB リクエストに失敗", error=str(exc))
        typer.echo(f"IGDB 検索に失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    allowed_categories = {0, 8, 9, 10, 11}
    title_lower = title.lower()
    exact_matches = [item for item in response.items if item.name.lower() == title_lower]

    candidates: list[IGDBGameDTO]
    if exact_matches:
        candidates = exact_matches
    else:
        candidates = [item for item in response.items if item.category in allowed_categories]
        if not candidates:
            candidates = list(response.items)

    filtered_items = tuple(candidates[:limit]) if limit > 0 else tuple(candidates)
    logger.info("IGDB 検索完了", results=len(filtered_items))

    if output is OutputFormat.JSON:
        _render_json(filtered_items)
    else:
        _render_table(filtered_items)
