"""埋め込みサービスの抽象レイヤー。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.types import ValueObject, utc_now

__all__ = [
    "EmbeddingJob",
    "EmbeddingVector",
    "EmbeddingServiceProtocol",
    "EmbeddingServiceError",
    "RateLimiter",
    "RetryPolicy",
    "RetryExecutor",
    "FailedEmbeddingRecord",
    "FailedEmbeddingQueue",
    "RetryableError",
    "normalize_vectors",
]


class EmbeddingServiceError(BaseAppError):
    """埋め込み処理における例外。"""

    default_message = "Embedding service failed"


@dataclass(slots=True)
class EmbeddingJob(ValueObject):
    """テキストをベクトル化するジョブ。"""

    content: str
    job_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: Mapping[str, Any] | None = None


@dataclass(slots=True)
class EmbeddingVector(ValueObject):
    """正規化済みの埋め込み結果。"""

    job_id: str
    values: tuple[float, ...]
    model: str
    created_at: datetime = field(default_factory=utc_now)


class EmbeddingServiceProtocol(Protocol):
    """埋め込みサービスが満たすべきインターフェース。"""

    provider_name: str

    def embed(self, job: EmbeddingJob) -> EmbeddingVector:  # pragma: no cover - protocol
        """単一ジョブを処理する。"""

    def embed_many(  # pragma: no cover - protocol
        self,
        jobs: Sequence[EmbeddingJob],
    ) -> list[EmbeddingVector]:
        """バッチ処理を行う。"""


@dataclass(slots=True)
class RateLimiter:
    """単純なトークンバケット風のレート制御。"""

    rate_per_minute: int
    _timestamps: deque[float] = field(default_factory=deque)

    def acquire(self) -> None:
        window = 60.0
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > window:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.rate_per_minute and self._timestamps:
            sleep_for = window - (now - self._timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._timestamps.append(time.monotonic())


class RetryableError(Exception):
    """再試行対象であることを示す制御用エラー。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class RetryPolicy:
    """再試行ポリシー。"""

    max_attempts: int = 3
    backoff_factor: float = 0.5
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)
    retry_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)

    def backoff(self, attempt: int) -> float:
        return self.backoff_factor * (2 ** (attempt - 1))

    def allows(self, *, status_code: int | None = None, error: Exception | None = None) -> bool:
        if status_code is not None and status_code in self.retry_statuses:
            return True
        if isinstance(error, RetryableError):
            if error.status_code is None:
                return True
            return error.status_code in self.retry_statuses
        if error is not None and isinstance(error, self.retry_exceptions):
            return True
        return False


T = TypeVar("T")


@dataclass(slots=True)
class RetryExecutor:
    """指定した処理を再試行付きで実行する。"""

    policy: RetryPolicy
    sleeper: Callable[[float], None] = time.sleep

    def run(self, operation: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if attempt >= self.policy.max_attempts:
                    raise
                status_code: int | None = None
                if isinstance(exc, RetryableError):
                    status_code = exc.status_code
                if not self.policy.allows(status_code=status_code, error=exc):
                    raise
                wait = self.policy.backoff(attempt)
                self.sleeper(wait)
        raise RuntimeError("retry executor exhausted without running operation") from last_error


@dataclass(slots=True)
class FailedEmbeddingRecord(ValueObject):
    """失敗ジョブとエラーを保持する DTO。"""

    job: EmbeddingJob
    error_message: str
    failed_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class FailedEmbeddingQueue:
    """単純な失敗キュー。"""

    max_size: int = 100
    _items: deque[FailedEmbeddingRecord] = field(default_factory=deque)

    def push(self, job: EmbeddingJob, error: Exception | str) -> None:
        message = str(error)
        record = FailedEmbeddingRecord(job=job, error_message=message)
        self._items.append(record)
        while len(self._items) > self.max_size:
            self._items.popleft()

    def drain(self) -> Iterable[FailedEmbeddingRecord]:
        while self._items:
            yield self._items.popleft()


def normalize_vectors(values: Iterable[float]) -> tuple[float, ...]:
    """埋め込みベクトルを tuple に正規化する。"""

    return tuple(float(v) for v in values)
