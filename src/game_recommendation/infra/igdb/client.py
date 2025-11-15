"""IGDB API クライアント実装。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from igdb.wrapper import IGDBWrapper
from requests import HTTPError

from game_recommendation.infra.igdb.dto import (
    IGDBGameResponse,
    IGDBResponseFormat,
    parse_games_from_payload,
)
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger


class IGDBWrapperProtocol(Protocol):
    """IGDBWrapper が満たすシンプルなプロトコル。"""

    def api_request(self, endpoint: str, query: str) -> bytes:
        """APICalypse クエリを実行してレスポンスを返す。"""


@dataclass(slots=True)
class IGDBRetryConfig:
    """リトライ・レート制御の設定。"""

    max_attempts: int = 3
    backoff_factor: float = 0.5
    retriable_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


@dataclass(slots=True, frozen=True)
class IGDBQuery:
    """APICalypse DSL を扱うための構造化クエリ。"""

    fields: tuple[str, ...] = ()
    where_clauses: tuple[str, ...] = ()
    sort_clause: tuple[str, str] | None = None
    limit_value: int | None = None
    offset_value: int | None = None
    search_term: str | None = None
    raw_statements: tuple[str, ...] = ()

    def to_apicalypse(self) -> str:
        parts: list[str] = []
        if self.fields:
            parts.append(f"fields {', '.join(self.fields)};")
        if self.search_term:
            parts.append(f'search "{self.search_term}";')
        if self.where_clauses:
            parts.append(f"where {' & '.join(self.where_clauses)};")
        if self.sort_clause:
            field, direction = self.sort_clause
            parts.append(f"sort {field} {direction};")
        if self.limit_value is not None:
            parts.append(f"limit {self.limit_value};")
        if self.offset_value is not None:
            parts.append(f"offset {self.offset_value};")
        parts.extend(f"{statement.rstrip(';')};" for statement in self.raw_statements if statement)
        return " ".join(parts)


class IGDBQueryBuilder:
    """APICalypse クエリを組み立てるビルダー。"""

    def __init__(self) -> None:
        self._fields: list[str] = []
        self._where: list[str] = []
        self._sort: tuple[str, str] | None = None
        self._limit: int | None = None
        self._offset: int | None = None
        self._search: str | None = None
        self._raw: list[str] = []

    def select(self, *fields: str) -> IGDBQueryBuilder:
        self._fields.extend(field for field in fields if field)
        return self

    def where(self, clause: str) -> IGDBQueryBuilder:
        if clause:
            self._where.append(clause)
        return self

    def sort(self, field: str, direction: str = "desc") -> IGDBQueryBuilder:
        if field:
            self._sort = (field, direction)
        return self

    def limit(self, value: int) -> IGDBQueryBuilder:
        if value >= 0:
            self._limit = value
        return self

    def offset(self, value: int) -> IGDBQueryBuilder:
        if value >= 0:
            self._offset = value
        return self

    def search(self, term: str) -> IGDBQueryBuilder:
        if term:
            self._search = term
        return self

    def raw(self, statement: str) -> IGDBQueryBuilder:
        if statement:
            self._raw.append(statement)
        return self

    def build(self) -> IGDBQuery:
        return IGDBQuery(
            fields=tuple(self._fields),
            where_clauses=tuple(self._where),
            sort_clause=self._sort,
            limit_value=self._limit,
            offset_value=self._offset,
            search_term=self._search,
            raw_statements=tuple(self._raw),
        )


class IGDBClientError(BaseAppError):
    """IGDB クライアント共通の例外。"""


class IGDBRateLimitError(IGDBClientError):
    """レート超過に起因するエラー。"""


class IGDBRequestError(IGDBClientError):
    """リトライ不能な HTTP エラー。"""


class IGDBClientProtocol(Protocol):
    """core/CLI 層から利用するためのプロトコル。"""

    def fetch_games(
        self,
        query: IGDBQuery,
        *,
        response_format: IGDBResponseFormat = IGDBResponseFormat.JSON,
    ) -> IGDBGameResponse:
        """ゲームエンドポイントへクエリを実行する。"""


class IGDBClient(IGDBClientProtocol):
    """IGDB API v4 公式ラッパーを包んだクライアント。"""

    def __init__(
        self,
        *,
        client_id: str,
        app_token: str,
        retry_config: IGDBRetryConfig | None = None,
        logger=None,
        wrapper_factory: Callable[[str, str], IGDBWrapperProtocol] | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._wrapper = (wrapper_factory or IGDBWrapper)(client_id, app_token)
        self._retry_config = retry_config or IGDBRetryConfig()
        self._sleep = sleep_func
        self._logger = logger or get_logger(__name__)

    def fetch_games(
        self,
        query: IGDBQuery,
        *,
        response_format: IGDBResponseFormat = IGDBResponseFormat.JSON,
    ) -> IGDBGameResponse:
        payload = self._perform_request(
            endpoint=f"games{response_format.endpoint_suffix}",
            query=query,
            response_format=response_format,
        )
        try:
            items = parse_games_from_payload(payload, response_format)
        except ValueError as exc:
            raise IGDBRequestError("Failed to parse IGDB response") from exc

        return IGDBGameResponse(items=items, raw=payload, format=response_format)

    def _perform_request(
        self,
        *,
        endpoint: str,
        query: IGDBQuery,
        response_format: IGDBResponseFormat,
    ) -> bytes:
        compiled_query = query.to_apicalypse()
        attempt = 0
        while True:
            attempt += 1
            try:
                self._logger.debug(
                    "igdb_request",
                    endpoint=endpoint,
                    attempt=attempt,
                    format=response_format.value,
                )
                return self._wrapper.api_request(endpoint, compiled_query)
            except HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if not self._should_retry(status_code, attempt):
                    if status_code == 429:
                        raise IGDBRateLimitError("IGDB API rate limit exceeded") from exc
                    msg = f"IGDB API request failed (status={status_code})"
                    raise IGDBRequestError(msg) from exc

                self._logger.warning(
                    "igdb_request_retry",
                    endpoint=endpoint,
                    attempt=attempt,
                    status_code=status_code,
                )
                self._sleep(self._retry_config.backoff_factor * attempt)

    def _should_retry(self, status_code: int | None, attempt: int) -> bool:
        if attempt >= self._retry_config.max_attempts:
            return False
        if status_code is None:
            return True
        return status_code in self._retry_config.retriable_statuses


def build_igdb_client(
    *,
    settings: AppSettings | None = None,
    retry_config: IGDBRetryConfig | None = None,
    logger=None,
) -> IGDBClient:
    """共有設定から IGDB クライアントを構築するファクトリ。"""

    app_settings = settings or get_settings()
    igdb_settings = app_settings.igdb
    token = igdb_settings.app_access_token or igdb_settings.client_secret
    return IGDBClient(
        client_id=igdb_settings.client_id,
        app_token=token.get_secret_value(),
        retry_config=retry_config,
        logger=logger,
    )


__all__ = [
    "IGDBClient",
    "IGDBClientError",
    "IGDBClientProtocol",
    "IGDBQuery",
    "IGDBQueryBuilder",
    "IGDBRateLimitError",
    "IGDBRequestError",
    "IGDBResponseFormat",
    "IGDBRetryConfig",
    "IGDBWrapperProtocol",
    "build_igdb_client",
]
