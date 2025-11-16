"""GameBuilderのテスト。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from game_recommendation.core.ingest.builder import (
    DefaultCoverUrlResolver,
    GameBuilder,
)
from game_recommendation.core.ingest.tag_resolver import ResolvedTag
from game_recommendation.infra.embeddings.base import (
    EmbeddingJob,
    EmbeddingVector,
)
from game_recommendation.infra.igdb.client import IGDBQuery, IGDBResponseFormat
from game_recommendation.infra.igdb.dto import IGDBGameDTO, IGDBGameResponse
from game_recommendation.shared.exceptions import Result


class FakeIGDBClient:
    """IGDB クライアントのモック。"""

    def __init__(self, games: dict[int, IGDBGameDTO]) -> None:
        self._games = games
        self.requests: list[tuple[IGDBQuery, IGDBResponseFormat]] = []

    def fetch_games(
        self, query: IGDBQuery, *, response_format: IGDBResponseFormat = IGDBResponseFormat.JSON
    ) -> IGDBGameResponse:
        self.requests.append((query, response_format))
        # whereクエリから ID を抽出（簡易実装）
        where_clause = query.where_clauses[0] if query.where_clauses else ""
        igdb_id = int(where_clause.split("=")[-1].strip())
        game = self._games.get(igdb_id)
        items = (game,) if game else ()
        return IGDBGameResponse(items=items, raw=b"[]", format=response_format)


class FakeTagResolver:
    """TagResolverのモック。"""

    def __init__(self, tags: dict[int, ResolvedTag]) -> None:
        self._tags = tags
        self.requests: list[Sequence[int]] = []

    def resolve(self, tag_numbers: Sequence[int]) -> Result[tuple[ResolvedTag, ...], object]:
        self.requests.append(tag_numbers)
        resolved = tuple(self._tags[num] for num in tag_numbers if num in self._tags)
        return Result.ok(resolved)


class FakeEmbeddingService:
    """EmbeddingServiceのモック。"""

    provider_name = "fake"

    def __init__(self, dimension: int = 768) -> None:
        self._dimension = dimension
        self.jobs: list[EmbeddingJob] = []

    def embed(self, job: EmbeddingJob) -> EmbeddingVector:
        return self.embed_many([job])[0]

    def embed_many(self, jobs: Sequence[EmbeddingJob]) -> list[EmbeddingVector]:
        self.jobs.extend(jobs)
        return [
            EmbeddingVector(
                job_id=job.job_id,
                values=tuple(float(i) for i in range(self._dimension)),
                model="fake-model",
            )
            for job in jobs
        ]


class FakeCoverUrlResolver:
    """CoverUrlResolverのモック。"""

    def resolve_cover_url(self, image_id: str | None) -> str | None:
        if not image_id:
            return None
        return f"https://example.com/covers/{image_id}.jpg"


@pytest.fixture()
def sample_game_dto() -> IGDBGameDTO:
    """サンプルゲームDTO。"""
    return IGDBGameDTO(
        id=1942,
        name="The Witcher 3: Wild Hunt",
        slug="the-witcher-3-wild-hunt",
        summary="A story-driven open world RPG set in a visually stunning fantasy universe.",
        first_release_date=datetime(2015, 5, 19, tzinfo=UTC),
        cover_image_id="co1rbi",
        platforms=(6, 48, 49),
        category=0,
        tags=(16777232, 33554433, 50331649),
    )


def test_build_success_with_embedding(sample_game_dto: IGDBGameDTO) -> None:
    """埋め込みありでビルドが成功する。"""
    igdb_client = FakeIGDBClient(games={sample_game_dto.id: sample_game_dto})
    tag_resolver = FakeTagResolver(
        tags={
            16777232: ResolvedTag(
                tag_number=16777232, slug="action", label="Action", tag_class="genre", igdb_id=16
            ),
            33554433: ResolvedTag(
                tag_number=33554433,
                slug="open-world",
                label="Open World",
                tag_class="theme",
                igdb_id=1,
            ),
        }
    )
    embedding_service = FakeEmbeddingService()
    cover_resolver = FakeCoverUrlResolver()

    builder = GameBuilder(
        igdb_client=igdb_client,
        tag_resolver=tag_resolver,
        embedding_service=embedding_service,
        cover_url_resolver=cover_resolver,
    )

    result = builder.build(sample_game_dto.id, generate_embedding=True)

    assert result.is_ok
    payload = result.unwrap()
    assert payload.igdb_game.id == sample_game_dto.id
    assert payload.igdb_game.name == sample_game_dto.name
    assert len(payload.tags) == 2
    assert payload.tags[0].slug == "action"
    assert payload.tags[1].slug == "open-world"
    assert payload.cover_url == "https://example.com/covers/co1rbi.jpg"
    assert payload.embedding is not None
    assert len(payload.embedding.title_embedding) == 768
    assert len(embedding_service.jobs) == 2


def test_build_success_without_embedding(sample_game_dto: IGDBGameDTO) -> None:
    """埋め込みなしでビルドが成功する。"""
    igdb_client = FakeIGDBClient(games={sample_game_dto.id: sample_game_dto})
    tag_resolver = FakeTagResolver(tags={})
    embedding_service = FakeEmbeddingService()

    builder = GameBuilder(
        igdb_client=igdb_client,
        tag_resolver=tag_resolver,
        embedding_service=embedding_service,
    )

    result = builder.build(sample_game_dto.id, generate_embedding=False)

    assert result.is_ok
    payload = result.unwrap()
    assert payload.embedding is None
    assert len(embedding_service.jobs) == 0


def test_build_game_not_found() -> None:
    """ゲームが見つからない場合、エラーを返す。"""
    igdb_client = FakeIGDBClient(games={})
    tag_resolver = FakeTagResolver(tags={})
    embedding_service = FakeEmbeddingService()

    builder = GameBuilder(
        igdb_client=igdb_client,
        tag_resolver=tag_resolver,
        embedding_service=embedding_service,
    )

    result = builder.build(9999, generate_embedding=False)

    assert result.is_err
    error = result.unwrap_err()
    assert "見つかりません" in str(error)


def test_build_with_no_tags(sample_game_dto: IGDBGameDTO) -> None:
    """タグがない場合でもビルドが成功する。"""
    game_no_tags = IGDBGameDTO(
        id=sample_game_dto.id,
        name=sample_game_dto.name,
        slug=sample_game_dto.slug,
        summary=sample_game_dto.summary,
        tags=(),
    )
    igdb_client = FakeIGDBClient(games={game_no_tags.id: game_no_tags})
    tag_resolver = FakeTagResolver(tags={})
    embedding_service = FakeEmbeddingService()

    builder = GameBuilder(
        igdb_client=igdb_client,
        tag_resolver=tag_resolver,
        embedding_service=embedding_service,
    )

    result = builder.build(game_no_tags.id, generate_embedding=False)

    assert result.is_ok
    payload = result.unwrap()
    assert len(payload.tags) == 0


def test_default_cover_url_resolver() -> None:
    """DefaultCoverUrlResolverが正しいURLを生成する。"""
    resolver = DefaultCoverUrlResolver()
    url = resolver.resolve_cover_url("co1rbi")
    assert url == "https://images.igdb.com/igdb/image/upload/t_cover_big/co1rbi.jpg"

    assert resolver.resolve_cover_url(None) is None
    assert resolver.resolve_cover_url("") is None


def test_default_cover_url_resolver_with_custom_size() -> None:
    """カスタムサイズでURLを生成する。"""
    resolver = DefaultCoverUrlResolver(size="t_1080p")
    url = resolver.resolve_cover_url("co1rbi")
    assert url == "https://images.igdb.com/igdb/image/upload/t_1080p/co1rbi.jpg"
