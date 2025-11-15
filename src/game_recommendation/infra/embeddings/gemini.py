"""Gemini API ベースの埋め込みサービス。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import google.generativeai as genai
import grpc
from google.api_core import exceptions as google_exceptions

from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import ConfigurationError
from game_recommendation.shared.logging import get_logger

from . import register_embedding_service
from .base import (
    EmbeddingJob,
    EmbeddingServiceError,
    EmbeddingServiceProtocol,
    EmbeddingVector,
    FailedEmbeddingQueue,
    RateLimiter,
    RetryableError,
    RetryExecutor,
    RetryPolicy,
    normalize_vectors,
)

_GRPC_STATUS_TO_HTTP: dict[grpc.StatusCode, int] = {
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.FAILED_PRECONDITION: 400,
    grpc.StatusCode.UNAUTHENTICATED: 401,
    grpc.StatusCode.PERMISSION_DENIED: 403,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.ALREADY_EXISTS: 409,
    grpc.StatusCode.ABORTED: 409,
    grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
    grpc.StatusCode.CANCELLED: 499,
    grpc.StatusCode.INTERNAL: 500,
    grpc.StatusCode.UNKNOWN: 500,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DATA_LOSS: 500,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
}


class EmbeddingClientProtocol(Protocol):
    """Gemini SDK 呼び出しを抽象化するクライアント。"""

    def embed(self, contents: Sequence[str]) -> dict[str, object]:  # pragma: no cover - protocol
        """埋め込み API を実行する。"""


@dataclass(slots=True)
class GeminiEmbeddingConfig:
    """Gemini API 呼び出しに利用する設定。"""

    api_key: str
    model: str
    rate_limit_per_minute: int = 60
    max_batch_size: int = 32
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> GeminiEmbeddingConfig:
        target = settings or get_settings()
        gemini_settings = target.gemini
        return cls(
            api_key=gemini_settings.api_key.get_secret_value(),
            model=gemini_settings.model,
        )

    @property
    def resolved_model(self) -> str:
        if self.model.startswith("models/"):
            return self.model
        return f"models/{self.model}"


class GeminiEmbeddingService(EmbeddingServiceProtocol):
    """Gemini を利用した埋め込みサービス。"""

    provider_name = "gemini"

    def __init__(
        self,
        config: GeminiEmbeddingConfig,
        *,
        embedding_client: EmbeddingClientProtocol | None = None,
        rate_limiter: RateLimiter | None = None,
        retry_executor: RetryExecutor | None = None,
        failure_queue: FailedEmbeddingQueue | None = None,
    ) -> None:
        self.config = config
        self._embedding_client = embedding_client or _GeminiEmbeddingClient(config)
        self._rate_limiter = rate_limiter or RateLimiter(config.rate_limit_per_minute)
        self._retry_executor = retry_executor or RetryExecutor(config.retry_policy)
        self._failure_queue = failure_queue or FailedEmbeddingQueue()
        self._logger = get_logger(__name__, provider=self.provider_name)

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> GeminiEmbeddingService:
        config = GeminiEmbeddingConfig.from_settings(settings)
        return cls(config=config)

    def embed(self, job: EmbeddingJob) -> EmbeddingVector:
        return self.embed_many([job])[0]

    def embed_many(self, jobs: Sequence[EmbeddingJob]) -> list[EmbeddingVector]:
        vectors: list[EmbeddingVector] = []
        for batch in self._chunk_jobs(jobs):
            try:
                vectors.extend(self._dispatch(batch))
            except Exception as exc:  # noqa: BLE001 - 上位でハンドリング
                self._handle_failure(batch, exc)
                raise
        return vectors

    def close(self) -> None:
        """Gemini SDK では明示的なリソース解放は不要。"""
        return None

    def _chunk_jobs(self, jobs: Sequence[EmbeddingJob]) -> Iterable[list[EmbeddingJob]]:
        current: list[EmbeddingJob] = []
        for job in jobs:
            current.append(job)
            if len(current) >= self.config.max_batch_size:
                yield current
                current = []
        if current:
            yield current

    def _dispatch(self, jobs: Sequence[EmbeddingJob]) -> list[EmbeddingVector]:
        self._rate_limiter.acquire()
        payload = self._execute_with_retry(jobs)
        return self._parse_response(jobs, payload)

    def _execute_with_retry(self, jobs: Sequence[EmbeddingJob]) -> dict[str, object]:
        contents = [job.content for job in jobs]

        def operation() -> dict[str, object]:
            try:
                return self._embedding_client.embed(contents)
            except google_exceptions.GoogleAPIError as exc:
                status_code = _extract_status_code(exc)
                if self._retry_executor.policy.allows(status_code=status_code, error=exc):
                    raise RetryableError(str(exc), status_code=status_code) from exc
                raise EmbeddingServiceError(str(exc)) from exc

        try:
            return self._retry_executor.run(operation)
        except RetryableError as exc:
            raise EmbeddingServiceError(str(exc)) from exc

    def _parse_response(
        self,
        jobs: Sequence[EmbeddingJob],
        response_payload: dict[str, object],
    ) -> list[EmbeddingVector]:
        embedding_data = response_payload.get("embedding")
        if not isinstance(embedding_data, list):
            raise EmbeddingServiceError("Gemini response payload is invalid")
        if len(jobs) == 1:
            return [self._make_vector(jobs[0], embedding_data)]
        if len(embedding_data) != len(jobs):
            raise EmbeddingServiceError("Gemini response count mismatch")
        vectors: list[EmbeddingVector] = []
        for job, values in zip(jobs, embedding_data, strict=True):
            if not isinstance(values, Iterable):
                raise EmbeddingServiceError("Gemini response did not include embedding values")
            vectors.append(self._make_vector(job, values))
        return vectors

    def _make_vector(self, job: EmbeddingJob, values: Iterable[float]) -> EmbeddingVector:
        normalized = normalize_vectors(values)
        return EmbeddingVector(job_id=job.job_id, values=normalized, model=self.config.model)

    def _handle_failure(self, jobs: Sequence[EmbeddingJob], error: Exception) -> None:
        for job in jobs:
            self._failure_queue.push(job, error)
        self._logger.error(
            "embedding_failed",
            job_ids=[job.job_id for job in jobs],
            error=str(error),
        )


class _GeminiEmbeddingClient(EmbeddingClientProtocol):
    """google-generativeai の thin wrapper。"""

    def __init__(self, config: GeminiEmbeddingConfig) -> None:
        self._api_key = config.api_key
        self._model_name = config.resolved_model
        self._configured = False

    def embed(self, contents: Sequence[str]) -> dict[str, object]:
        self._ensure_client()
        if len(contents) == 1:
            return genai.embed_content(model=self._model_name, content=contents[0])
        return genai.embed_content(model=self._model_name, content=list(contents))

    def _ensure_client(self) -> None:
        if not self._configured:
            genai.configure(api_key=self._api_key)
            self._configured = True


def _extract_status_code(exc: google_exceptions.GoogleAPIError) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    if code in _GRPC_STATUS_TO_HTTP:
        return _GRPC_STATUS_TO_HTTP[code]
    if hasattr(code, "value"):
        value = code.value
        if isinstance(value, (tuple, list)) and value:
            first = value[0]
            if isinstance(first, int):
                return first
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def _register_default() -> None:
    def factory(settings: AppSettings | None = None) -> GeminiEmbeddingService:
        merged = settings or get_settings()
        api_key = merged.gemini.api_key.get_secret_value()
        if not api_key:
            raise ConfigurationError("Gemini API key is missing")
        model = merged.gemini.model
        config = GeminiEmbeddingConfig(api_key=api_key, model=model)
        return GeminiEmbeddingService(config=config)

    register_embedding_service(GeminiEmbeddingService.provider_name, factory)


_register_default()


__all__ = [
    "GeminiEmbeddingConfig",
    "GeminiEmbeddingService",
]
