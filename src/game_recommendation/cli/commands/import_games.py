from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from structlog.stdlib import BoundLogger

from game_recommendation.core.ingest.builder import GameBuilder, GameBuilderError
from game_recommendation.core.ingest.models import EmbeddedGamePayload, GameTagPayload
from game_recommendation.core.ingest.tag_resolver import GameTagRepositoryProtocol, TagResolver
from game_recommendation.infra.db.models import (
    GameEmbedding,
    GameTag,
    GameTagLink,
    IgdbGame,
    UserFavoriteGame,
)
from game_recommendation.infra.db.repositories import SQLAlchemyGameTagRepository
from game_recommendation.infra.db.session import DatabaseSessionManager
from game_recommendation.infra.embeddings import get_default_embedding_service
from game_recommendation.infra.igdb import build_igdb_client
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.logging import configure_logging, get_logger

from .igdb import OutputFormat


class ImportStatus(str, Enum):
    """取り込みステータス。"""

    IMPORTED = "imported"
    SKIPPED = "skipped"
    DRY_RUN = "dry-run"
    FAILED = "failed"


@dataclass(slots=True)
class ImportItem:
    """1件の取り込み結果。"""

    igdb_id: int
    title: str | None
    status: ImportStatus
    tags: int
    has_embedding: bool
    message: str | None = None


@dataclass(slots=True)
class ImportContext:
    builder: GameBuilder
    db_manager: DatabaseSessionManager | None
    settings: AppSettings


class InMemoryTagRepository(GameTagRepositoryProtocol):
    """dry-run 用のメモリ内タグリポジトリ。"""

    def __init__(self) -> None:
        self._records: dict[tuple[str, int], GameTag] = {}

    def fetch_by_igdb_ids(self, *, tag_class: str, igdb_ids: Sequence[int]) -> dict[int, GameTag]:
        if not igdb_ids:
            return {}
        return {
            igdb_id: record
            for (klass, igdb_id), record in self._records.items()
            if klass == tag_class and igdb_id in igdb_ids
        }

    def save_all(self, tags: Sequence[GameTag]) -> None:
        for tag in tags:
            if tag.igdb_id is None:
                continue
            self._records[(tag.tag_class, int(tag.igdb_id))] = tag


app = typer.Typer(
    help="IGDB ID からゲームデータを全テーブルへ取り込むコマンド",
    invoke_without_command=True,
    no_args_is_help=True,
)


def _parse_igdb_ids(raw_ids: str) -> tuple[int, ...]:
    parts = [part.strip() for part in raw_ids.split(",")]
    seen: set[int] = set()
    igdb_ids: list[int] = []
    for part in parts:
        if not part:
            continue
        try:
            igdb_id = int(part)
        except ValueError as exc:  # noqa: PERF203 - 正確な例外が重要
            raise typer.BadParameter(f"IGDB ID は整数で指定してください: {part}") from exc
        if igdb_id in seen:
            continue
        seen.add(igdb_id)
        igdb_ids.append(igdb_id)
    return tuple(igdb_ids)


def _create_tag_repository(
    *,
    dry_run: bool,
    db_manager: DatabaseSessionManager | None,
) -> GameTagRepositoryProtocol:
    if dry_run:
        return InMemoryTagRepository()
    if db_manager is None:
        msg = "db_manager is required when dry_run is False"
        raise ValueError(msg)
    return SQLAlchemyGameTagRepository(db_manager.session_factory)


def _prepare_context(
    *, dry_run: bool, settings: AppSettings | None, logger: BoundLogger
) -> ImportContext:
    app_settings = settings or get_settings()
    db_manager = None if dry_run else DatabaseSessionManager(settings=app_settings, logger=logger)

    igdb_client = build_igdb_client(settings=app_settings, logger=logger)
    tag_repository = _create_tag_repository(dry_run=dry_run, db_manager=db_manager)
    tag_resolver = TagResolver(repository=tag_repository, igdb_client=igdb_client, logger=logger)
    embedding_service = get_default_embedding_service(app_settings)

    builder = GameBuilder(
        igdb_client=igdb_client,
        tag_resolver=tag_resolver,
        embedding_service=embedding_service,
        logger=logger,
    )
    return ImportContext(builder=builder, db_manager=db_manager, settings=app_settings)


def _build_item_from_payload(
    payload: EmbeddedGamePayload, status: ImportStatus, message: str | None = None
) -> ImportItem:
    return ImportItem(
        igdb_id=payload.igdb_game.id,
        title=payload.igdb_game.name,
        status=status,
        tags=len(payload.tags),
        has_embedding=payload.embedding is not None,
        message=message,
    )


def _ensure_tags(
    session: Session,
    tag_payloads: Sequence[GameTagPayload],
    logger: BoundLogger,
) -> dict[tuple[str, str], int]:
    tag_id_lookup: dict[tuple[str, str], int] = {}
    created = 0
    for tag_payload in tag_payloads:
        existing = session.scalar(
            select(GameTag).where(
                GameTag.slug == tag_payload.slug, GameTag.tag_class == tag_payload.tag_class
            )
        )
        if existing:
            tag_id_lookup[tag_payload.identity] = int(existing.id)
            continue
        record = tag_payload.to_game_tag()
        session.add(record)
        session.flush()
        tag_id_lookup[tag_payload.identity] = int(record.id)
        created += 1
    logger.info("import_tags_resolved", total=len(tag_payloads), created=created)
    return tag_id_lookup


def _ensure_tag_links(
    session: Session,
    game_record_id: int,
    payload: EmbeddedGamePayload,
    tag_id_lookup: dict[tuple[str, str], int],
) -> None:
    for link in payload.to_game_tag_link(game_record_id, tag_id_lookup):
        exists = session.scalar(
            select(GameTagLink).where(
                GameTagLink.game_id == link.game_id, GameTagLink.tag_id == link.tag_id
            )
        )
        if exists:
            continue
        session.add(link)


def _ensure_embedding(session: Session, payload: EmbeddedGamePayload) -> None:
    if payload.embedding is None:
        return
    game_id = str(payload.igdb_game.id)
    exists = session.scalar(select(GameEmbedding).where(GameEmbedding.game_id == game_id))
    if exists:
        return
    session.add(payload.to_game_embedding())


def _ensure_favorite(session: Session, game_record_id: int, payload: EmbeddedGamePayload) -> None:
    exists = session.scalar(
        select(UserFavoriteGame).where(UserFavoriteGame.game_id == game_record_id)
    )
    if exists:
        return
    session.add(payload.to_user_favorite_game(game_record_id))


def _persist_payload(
    session: Session,
    payload: EmbeddedGamePayload,
    logger: BoundLogger,
) -> ImportItem:
    igdb_id = payload.igdb_game.id
    existing_game = session.scalar(select(IgdbGame).where(IgdbGame.igdb_id == igdb_id))
    if existing_game:
        return ImportItem(
            igdb_id=igdb_id,
            title=existing_game.title,
            status=ImportStatus.SKIPPED,
            tags=len(payload.tags),
            has_embedding=payload.embedding is not None,
            message="既存レコードをスキップ",
        )

    game_record = payload.to_igdb_game()
    session.add(game_record)
    session.flush()

    tag_id_lookup = _ensure_tags(session, payload.tags, logger)
    _ensure_tag_links(session, int(game_record.id), payload, tag_id_lookup)
    _ensure_embedding(session, payload)
    _ensure_favorite(session, int(game_record.id), payload)

    logger.info("import_game_persisted", igdb_id=igdb_id, game_record_id=int(game_record.id))
    return ImportItem(
        igdb_id=igdb_id,
        title=payload.igdb_game.name,
        status=ImportStatus.IMPORTED,
        tags=len(payload.tags),
        has_embedding=payload.embedding is not None,
    )


def _persist_all(
    *,
    db_manager: DatabaseSessionManager,
    payloads: Sequence[EmbeddedGamePayload],
    logger: BoundLogger,
) -> list[ImportItem]:
    results: list[ImportItem] = []
    with db_manager.transaction() as session:
        for payload in payloads:
            results.append(_persist_payload(session, payload, logger))
    return results


def _render_table(items: Iterable[ImportItem]) -> None:
    console = Console(force_terminal=False, color_system=None)
    table = Table(title="IGDB Import Results")
    table.add_column("IGDB ID", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Status")
    table.add_column("Tags")
    table.add_column("Embedding")
    table.add_column("Message")

    for item in items:
        table.add_row(
            str(item.igdb_id),
            item.title or "-",
            item.status.value,
            str(item.tags),
            "yes" if item.has_embedding else "no",
            item.message or "-",
        )

    console.print(table)


def _render_json(items: Iterable[ImportItem]) -> None:
    payload = [
        {
            "igdb_id": item.igdb_id,
            "title": item.title,
            "status": item.status.value,
            "tags": item.tags,
            "has_embedding": item.has_embedding,
            "message": item.message,
        }
        for item in items
    ]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _render_output(items: Iterable[ImportItem], output: OutputFormat) -> None:
    if output is OutputFormat.JSON:
        _render_json(items)
    else:
        _render_table(items)


def _handle_build_failure(igdb_id: int, error: GameBuilderError, logger: BoundLogger) -> ImportItem:
    logger.error("import_builder_failed", igdb_id=igdb_id, error=str(error))
    return ImportItem(
        igdb_id=igdb_id,
        title=None,
        status=ImportStatus.FAILED,
        tags=0,
        has_embedding=False,
        message=str(error),
    )


@app.callback()
def import_games(
    igdb_ids: Annotated[
        str,
        typer.Option(
            "--igdb-ids",
            "-i",
            help="カンマ区切りの IGDB ID (例: 123,456)",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="DBへ書き込まず生成データのみ確認する"),
    ] = False,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            "-o",
            case_sensitive=False,
            help="出力形式(table/json)",
        ),
    ] = OutputFormat.TABLE,
) -> None:
    """IGDB ID を指定してゲームデータを全テーブルへ挿入する。"""

    app_settings = get_settings()
    configure_logging(level=app_settings.log_level)
    logger = get_logger("cli.import", dry_run=dry_run)
    try:
        parsed_ids = _parse_igdb_ids(igdb_ids)
    except typer.BadParameter as exc:
        raise typer.Exit(code=1) from exc

    if not parsed_ids:
        typer.echo("IGDB ID を1つ以上指定してください。")
        raise typer.Exit(code=1)

    context = _prepare_context(dry_run=dry_run, settings=app_settings, logger=logger)

    built_payloads: list[EmbeddedGamePayload] = []
    results: list[ImportItem] = []

    for igdb_id in parsed_ids:
        build_result = context.builder.build(igdb_id)
        if build_result.is_err:
            results.append(_handle_build_failure(igdb_id, build_result.unwrap_err(), logger))
            continue
        built_payloads.append(build_result.unwrap())

    if dry_run:
        results.extend(
            _build_item_from_payload(payload, ImportStatus.DRY_RUN) for payload in built_payloads
        )
        _render_output(results, output)
        exit_code = 0 if all(item.status is not ImportStatus.FAILED for item in results) else 1
        raise typer.Exit(code=exit_code)

    if context.db_manager is None:
        typer.echo("DB マネージャーの初期化に失敗しました。")
        raise typer.Exit(code=1)

    try:
        persisted = _persist_all(
            db_manager=context.db_manager, payloads=built_payloads, logger=logger
        )
        results.extend(persisted)
    except SQLAlchemyError as exc:
        logger.error("import_transaction_failed", error=str(exc))
        for payload in built_payloads:
            results.append(
                _build_item_from_payload(
                    payload,
                    ImportStatus.FAILED,
                    message="DB 挿入に失敗したためロールバックしました",
                )
            )
        _render_output(results, output)
        raise typer.Exit(code=1) from exc

    _render_output(results, output)
    if any(item.status is ImportStatus.FAILED for item in results):
        raise typer.Exit(code=1)
