from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from structlog.stdlib import BoundLogger

from game_recommendation.core.favorites.loader import FavoriteLoader, FavoriteLoaderError
from game_recommendation.core.favorites.query import (
    EmbeddingSimilarityStrategy,
    TagSimilarityStrategy,
    _extract_storyline_embedding,
    _extract_summary_embedding,
    _extract_title_embedding,
    _safe_score,
    _tag_keys_from_payload,
)
from game_recommendation.core.ingest.builder import GameBuilder
from game_recommendation.core.ingest.models import EmbeddedGamePayload
from game_recommendation.core.ingest.tag_resolver import GameTagRepositoryProtocol, TagResolver
from game_recommendation.core.prompting.builder import (
    RecommendationPromptBuilder,
    RecommendationPromptInput,
    RecommendationPromptResult,
    SimilarGameExample,
)
from game_recommendation.infra.db.session import DatabaseSessionManager
from game_recommendation.infra.embeddings import get_default_embedding_service
from game_recommendation.infra.igdb import build_igdb_client
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger


class InMemoryTagRepository(GameTagRepositoryProtocol):
    """タグの永続化を伴わないメモリ内リポジトリ。"""

    def __init__(self) -> None:
        self._records: dict[tuple[str, int], object] = {}

    def fetch_by_igdb_ids(self, *, tag_class: str, igdb_ids: Sequence[int]) -> dict[int, object]:
        return {
            igdb_id: record
            for (klass, igdb_id), record in self._records.items()
            if klass == tag_class and igdb_id in igdb_ids
        }

    def save_all(self, tags: Sequence[object]) -> None:
        for tag in tags:
            try:
                tag_class = tag.tag_class
                igdb_id = tag.igdb_id
            except AttributeError as exc:
                raise ValueError("tag must have tag_class and igdb_id") from exc
            if igdb_id is None:
                continue
            self._records[(tag_class, int(igdb_id))] = tag


@dataclass(slots=True)
class PromptContext:
    builder: GameBuilder
    favorites_loader: FavoriteLoader
    settings: AppSettings
    logger: BoundLogger = field(
        default_factory=lambda: get_logger(__name__, component="prompt-cli")
    )


app = typer.Typer(help="IGDB ID から推薦判定プロンプトを生成するコマンド")


def _prepare_context(settings: AppSettings, logger: BoundLogger) -> PromptContext:
    igdb_client = build_igdb_client(settings=settings, logger=logger)
    tag_resolver = TagResolver(
        repository=InMemoryTagRepository(), igdb_client=igdb_client, logger=logger
    )
    embedding_service = get_default_embedding_service(settings)

    builder = GameBuilder(
        igdb_client=igdb_client,
        tag_resolver=tag_resolver,
        embedding_service=embedding_service,
        logger=logger,
    )

    db_manager = DatabaseSessionManager(settings=settings, logger=logger)
    favorites_loader = FavoriteLoader(session_factory=db_manager.session_factory, logger=logger)

    return PromptContext(
        builder=builder, favorites_loader=favorites_loader, settings=settings, logger=logger
    )


def _rank_candidates(
    candidates: Sequence[EmbeddedGamePayload],
    strategy: object,
    *,
    top_n: int,
) -> tuple[SimilarGameExample, ...]:
    scored: list[tuple[EmbeddedGamePayload, float]] = []
    for payload in candidates:
        score = _safe_score(strategy, payload)
        if math.isinf(score) and score < 0:
            continue
        scored.append((payload, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return tuple(SimilarGameExample(game=payload, score=score) for payload, score in scored[:top_n])


def _select_tag_similar(
    target: EmbeddedGamePayload, candidates: Sequence[EmbeddedGamePayload], *, top_n: int
) -> tuple[SimilarGameExample, ...]:
    tag_keys = _tag_keys_from_payload(target.tags)
    if not tag_keys or not candidates:
        return tuple()

    strategy = TagSimilarityStrategy(tag_keys)
    return _rank_candidates(candidates, strategy, top_n=top_n)


def _select_embedding_similar(
    candidates: Sequence[EmbeddedGamePayload],
    embedding: Sequence[float] | None,
    selector: Callable[[EmbeddedGamePayload], Sequence[float] | None],
    *,
    top_n: int,
) -> tuple[SimilarGameExample, ...]:
    if embedding is None or not candidates:
        return tuple()

    vector = tuple(float(value) for value in embedding)
    if not vector:
        return tuple()

    strategy = EmbeddingSimilarityStrategy(vector, selector=selector)
    return _rank_candidates(candidates, strategy, top_n=top_n)


def _build_prompt_input(
    target: EmbeddedGamePayload,
    favorites: Sequence[EmbeddedGamePayload],
    *,
    top_n: int,
) -> RecommendationPromptInput:
    candidates = [item for item in favorites if item.igdb_game.id != target.igdb_game.id]

    tag_similar = _select_tag_similar(target, candidates, top_n=top_n)
    title_similar = _select_embedding_similar(
        candidates,
        target.embedding.title_embedding if target.embedding else None,
        _extract_title_embedding,
        top_n=top_n,
    )
    storyline_similar = _select_embedding_similar(
        candidates,
        target.embedding.storyline_embedding if target.embedding else None,
        _extract_storyline_embedding,
        top_n=top_n,
    )
    summary_similar = _select_embedding_similar(
        candidates,
        target.embedding.summary_embedding if target.embedding else None,
        _extract_summary_embedding,
        top_n=top_n,
    )

    return RecommendationPromptInput(
        target=target,
        tag_similar=tag_similar,
        title_similar=title_similar,
        storyline_similar=storyline_similar,
        summary_similar=summary_similar,
    )


def _generate_prompt(
    *, context: PromptContext, igdb_id: int, top_n: int, logger: BoundLogger
) -> RecommendationPromptResult:
    target_result = context.builder.build(igdb_id)
    if target_result.is_err:
        error = target_result.unwrap_err()
        logger.error("prompt_target_build_failed", error=str(error))
        typer.echo(f"IGDB ID {igdb_id} の取得に失敗しました: {error}")
        raise typer.Exit(code=1)
    target = target_result.unwrap()

    try:
        favorites = context.favorites_loader.load()
    except FavoriteLoaderError as exc:
        logger.error("prompt_favorites_load_failed", error=str(exc))
        typer.echo(f"お気に入りデータの取得に失敗しました: {exc}")
        raise typer.Exit(code=2) from exc

    try:
        prompt_input = _build_prompt_input(target, favorites, top_n=top_n)
    except (BaseAppError, ValueError) as exc:
        logger.error("prompt_input_build_failed", error=str(exc))
        typer.echo(f"プロンプト入力の生成に失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    builder = RecommendationPromptBuilder()
    try:
        result = builder.build(prompt_input)
    except FileNotFoundError as exc:
        logger.error("prompt_template_missing", error=str(exc))
        typer.echo(f"テンプレートの読み込みに失敗しました: {exc}")
        raise typer.Exit(code=1) from exc
    return result


@app.command()
def generate(
    igdb_id: Annotated[int, typer.Option("--igdb-id", "-i", help="プロンプト対象のIGDB ID")],
    output_file: Annotated[
        Path | None,
        typer.Option(
            "--output-file",
            "-o",
            file_okay=True,
            dir_okay=False,
            writable=True,
            resolve_path=True,
            help="生成したプロンプトを書き出すファイルパス",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", min=1, max=20, help="類似ゲームを出力する最大件数"),
    ] = 3,
) -> None:
    """IGDB ID を基に判定用プロンプトを生成する。"""

    logger = get_logger("cli.prompt.generate", igdb_id=igdb_id)
    try:
        settings = get_settings()
        context = _prepare_context(settings=settings, logger=logger)
    except BaseAppError as exc:
        logger.error("prompt_context_settings_failed", error=str(exc))
        typer.echo(f"設定の読み込みに失敗しました: {exc}")
        raise typer.Exit(code=1) from exc

    result = _generate_prompt(context=context, igdb_id=igdb_id, top_n=limit, logger=logger)

    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(result.prompt, encoding="utf-8")

    typer.echo(result.prompt)
