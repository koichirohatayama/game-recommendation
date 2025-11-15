"""GeminiEmbeddingService の基本挙動を確認するテスト。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from google.api_core import exceptions as google_exceptions

from game_recommendation.infra.embeddings.base import (
    EmbeddingJob,
    EmbeddingServiceError,
    FailedEmbeddingQueue,
    RetryExecutor,
    RetryPolicy,
)
from game_recommendation.infra.embeddings.gemini import (
    GeminiEmbeddingConfig,
    GeminiEmbeddingService,
)


class _NoopRateLimiter:
    def acquire(self) -> None:  # pragma: no cover - 単純なテストダブル
        return


@dataclass
class _FakeEmbeddingClient:
    responses: list[dict[str, object] | Exception]
    calls: list[list[str]] = field(default_factory=list)

    def embed(self, contents: Sequence[str]) -> dict[str, object]:
        self.calls.append(list(contents))
        if not self.responses:
            msg = "No more responses configured"
            raise RuntimeError(msg)
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _build_service(
    client: _FakeEmbeddingClient,
    *,
    config: GeminiEmbeddingConfig | None = None,
) -> tuple[GeminiEmbeddingService, FailedEmbeddingQueue]:
    cfg = config or GeminiEmbeddingConfig(api_key="test", model="embedding-001")
    failure_queue = FailedEmbeddingQueue()
    retry_executor = RetryExecutor(cfg.retry_policy, sleeper=lambda _: None)
    service = GeminiEmbeddingService(
        config=cfg,
        embedding_client=client,
        rate_limiter=_NoopRateLimiter(),
        retry_executor=retry_executor,
        failure_queue=failure_queue,
    )
    return service, failure_queue


def test_embed_many_success() -> None:
    jobs = [EmbeddingJob(content="foo"), EmbeddingJob(content="bar")]
    client = _FakeEmbeddingClient(responses=[{"embedding": [[0.1, 0.2], [0.3, 0.4]]}])

    service, queue = _build_service(client)
    vectors = service.embed_many(jobs)

    assert len(vectors) == 2
    assert vectors[0].values == (0.1, 0.2)
    assert client.calls[0] == ["foo", "bar"]
    assert list(queue.drain()) == []


def test_embed_failure_is_enqueued() -> None:
    job = EmbeddingJob(content="ng")
    client = _FakeEmbeddingClient(responses=[google_exceptions.InvalidArgument("bad request")])

    service, queue = _build_service(client)
    with pytest.raises(EmbeddingServiceError):
        service.embed(job)

    failures = list(queue.drain())
    assert len(failures) == 1
    assert failures[0].job.job_id == job.job_id
    assert "bad request" in failures[0].error_message


def test_retry_on_transient_error() -> None:
    job = EmbeddingJob(content="retry")
    policy = RetryPolicy(max_attempts=2, backoff_factor=0.0)
    config = GeminiEmbeddingConfig(api_key="test", model="embedding-001", retry_policy=policy)
    client = _FakeEmbeddingClient(
        responses=[
            google_exceptions.ServiceUnavailable("busy"),
            {"embedding": [0.42]},
        ]
    )

    service, queue = _build_service(client, config=config)
    vector = service.embed(job)

    assert len(client.calls) == 2
    assert vector.values == (0.42,)
    assert list(queue.drain()) == []
