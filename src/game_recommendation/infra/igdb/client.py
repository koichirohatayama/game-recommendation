"""IGDB API クライアント実装。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import httpx
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
class IGDBAccessToken:
    """IGDB API へアクセスするためのアクセストークン。"""

    access_token: str
    expires_at: datetime | None


class TwitchOAuthClient:
    """Twitch OAuth2 (client credentials) でアクセストークンを取得するクライアント。"""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_url: str,
        http_post: Callable[..., httpx.Response] = httpx.post,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._http_post = http_post

    def fetch_app_access_token(self) -> IGDBAccessToken:
        response = self._http_post(
            self._token_url,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        access_token = payload["access_token"]
        expires_in = payload.get("expires_in")
        expires_at = (
            datetime.now(datetime.UTC) + timedelta(seconds=int(expires_in))
            if isinstance(expires_in, (int, float))
            else None
        )
        return IGDBAccessToken(access_token=access_token, expires_at=expires_at)


class IGDBAccessTokenProvider:
    """アクセストークンのキャッシュと有効期限管理を行うプロバイダー。"""

    def __init__(
        self,
        *,
        oauth_client: TwitchOAuthClient,
        refresh_margin: timedelta,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._oauth_client = oauth_client
        self._refresh_margin = refresh_margin
        self._clock = clock or (lambda: datetime.now(datetime.UTC))
        self._cached_token: IGDBAccessToken | None = None

    def get_token(self) -> IGDBAccessToken:
        now = self._clock()
        if self._cached_token and not self._should_refresh(self._cached_token, now):
            return self._cached_token

        self._cached_token = self._oauth_client.fetch_app_access_token()
        return self._cached_token

    def _should_refresh(self, token: IGDBAccessToken, now: datetime) -> bool:
        if token.expires_at is None:
            return False
        return token.expires_at - self._refresh_margin <= now


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
        token_provider: IGDBAccessTokenProvider,
        retry_config: IGDBRetryConfig | None = None,
        logger=None,
        wrapper_factory: Callable[[str, str], IGDBWrapperProtocol] | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client_id = client_id
        self._token_provider = token_provider
        self._wrapper_factory = wrapper_factory or IGDBWrapper
        self._wrapper: IGDBWrapperProtocol | None = None
        self._cached_token_value: str | None = None
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
                wrapper = self._get_wrapper()
                return wrapper.api_request(endpoint, compiled_query)
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

    def _get_wrapper(self) -> IGDBWrapperProtocol:
        token = self._token_provider.get_token()
        if self._wrapper is None or token.access_token != self._cached_token_value:
            self._wrapper = self._wrapper_factory(self._client_id, token.access_token)
            self._cached_token_value = token.access_token
        return self._wrapper


def build_igdb_client(
    *,
    settings: AppSettings | None = None,
    retry_config: IGDBRetryConfig | None = None,
    logger=None,
) -> IGDBClient:
    """共有設定から IGDB クライアントを構築するファクトリ。"""

    app_settings = settings or get_settings()
    igdb_settings = app_settings.igdb
    oauth_client = TwitchOAuthClient(
        client_id=igdb_settings.client_id,
        client_secret=igdb_settings.client_secret.get_secret_value(),
        token_url=str(igdb_settings.token_url),
    )
    token_provider = IGDBAccessTokenProvider(
        oauth_client=oauth_client,
        refresh_margin=timedelta(seconds=igdb_settings.refresh_margin_seconds),
    )
    return IGDBClient(
        client_id=igdb_settings.client_id,
        token_provider=token_provider,
        retry_config=retry_config,
        logger=logger,
    )


__all__ = [
    "IGDBAccessToken",
    "IGDBAccessTokenProvider",
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
    "TwitchOAuthClient",
    "build_igdb_client",
]
