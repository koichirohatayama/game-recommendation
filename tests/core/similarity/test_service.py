"""SimilarityService の単体テスト。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from game_recommendation.core.similarity.dto import SimilarityQuery
from game_recommendation.core.similarity.service import (
    SimilarityService,
    SimilarityServiceError,
)
from game_recommendation.infra.db.embedding_repository import (
    EmbeddingRepositoryError,
    GameEmbeddingSearchResult,
)
from game_recommendation.infra.embeddings.base import (
    EmbeddingJob,
    EmbeddingServiceError,
    EmbeddingVector,
)


def _build_search_result(
    game_id: str,
    *,
    distance: float,
    tags: Sequence[str] | None = None,
    genres: Sequence[str] | None = None,
    summary: str | None = None,
    title: str | None = None,
    keywords: Sequence[str] | None = None,
) -> GameEmbeddingSearchResult:
    now = datetime.now(UTC)
    metadata = {
        "title": title or f"Game {game_id}",
        "summary": summary,
        "tags": list(tags or ()),
        "genres": list(genres or ()),
        "keywords": list(keywords or ()),
    }
    return GameEmbeddingSearchResult(
        game_id=game_id,
        dimension=2,
        title_embedding=(0.1, 0.2),
        storyline_embedding=(0.2, 0.1),
        summary_embedding=(0.3, 0.2),
        metadata=metadata,
        created_at=now,
        updated_at=now,
        distance=distance,
    )


@dataclass
class FakeEmbeddingService:
    vector: tuple[float, ...] = (0.1, 0.2)
    error: Exception | None = None

    provider_name: str = "fake"

    def embed(self, job: EmbeddingJob) -> EmbeddingVector:
        if self.error:
            raise self.error
        return EmbeddingVector(job_id=job.job_id, values=self.vector, model="fake-model")


@dataclass
class FakeRepository:
    results: list[GameEmbeddingSearchResult]
    error: Exception | None = None

    def search_similar(
        self, query_embedding: Sequence[float], *, limit: int = 10
    ) -> list[GameEmbeddingSearchResult]:
        if self.error:
            raise self.error
        return list(self.results[:limit])


def test_find_similar_applies_adjustments_and_sorts() -> None:
    repo = FakeRepository(
        results=[
            _build_search_result(
                "1",
                distance=0.4,
                tags=["RPG", "Fantasy"],
                genres=["Adventure"],
                summary="Embark on an epic RPG quest across fantasy worlds.",
                keywords=["dragon"],
            ),
            _build_search_result(
                "2",
                distance=0.3,
                tags=["Shooter"],
                genres=["Action"],
                summary="Fast paced shooter.",
            ),
        ]
    )
    service = SimilarityService(embedding_service=FakeEmbeddingService(), repository=repo)
    query = SimilarityQuery(
        title="Epic Fantasy Adventure",
        summary="An epic RPG quest filled with dragons and fantasy.",
        tags=("RPG", "Fantasy"),
        genres=("Adventure",),
        focus_keywords=("dragon", "quest"),
        limit=5,
    )

    result = service.find_similar(query)

    assert result.is_ok
    value = result.unwrap()
    assert len(value.matches) == 2
    top = value.matches[0]
    assert top.candidate.game_id == "1"
    assert top.score >= top.base_score
    assert any(reason.startswith("tag_overlap") for reason in top.reasons)
    assert any(reason.startswith("summary_overlap") for reason in top.reasons)


def test_missing_metadata_applies_penalty() -> None:
    repo = FakeRepository(
        results=[
            _build_search_result(
                "10",
                distance=0.2,
                tags=[],
                genres=[],
                summary=None,
            )
        ]
    )
    service = SimilarityService(embedding_service=FakeEmbeddingService(), repository=repo)
    query = SimilarityQuery(
        title="Quest",
        summary="Story focused adventure",
        tags=("Story",),
        genres=("Adventure",),
        limit=1,
    )

    result = service.find_similar(query)

    assert result.is_ok
    match = result.unwrap().matches[0]
    assert match.score < match.base_score
    assert any(reason.startswith("penalty:") for reason in match.reasons)


def test_embedding_failure_returns_error_result() -> None:
    service = SimilarityService(
        embedding_service=FakeEmbeddingService(error=EmbeddingServiceError("boom")),
        repository=FakeRepository(results=[]),
    )
    query = SimilarityQuery(title="Any", limit=1)

    result = service.find_similar(query)

    assert result.is_err
    error = result.unwrap_err()
    assert isinstance(error, SimilarityServiceError)
    assert "boom" in str(error)


def test_repository_failure_returns_error_result() -> None:
    repo_error = EmbeddingRepositoryError("db down")
    service = SimilarityService(
        embedding_service=FakeEmbeddingService(),
        repository=FakeRepository(results=[], error=repo_error),
    )
    query = SimilarityQuery(title="Any", limit=1)

    result = service.find_similar(query)

    assert result.is_err
    error = result.unwrap_err()
    assert isinstance(error, SimilarityServiceError)
    assert "db down" in str(error)
