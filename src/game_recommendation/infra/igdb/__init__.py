"""IGDB API 向け infra 層パッケージ。"""

from .client import (
    IGDBAccessToken,
    IGDBAccessTokenProvider,
    IGDBClient,
    IGDBClientError,
    IGDBClientProtocol,
    IGDBQuery,
    IGDBQueryBuilder,
    IGDBRateLimitError,
    IGDBRequestError,
    IGDBResponseFormat,
    IGDBRetryConfig,
    IGDBWrapperProtocol,
    TwitchOAuthClient,
    build_igdb_client,
)
from .dto import IGDBGameDTO, IGDBGameResponse

__all__ = [
    "IGDBClient",
    "IGDBClientError",
    "IGDBClientProtocol",
    "IGDBAccessToken",
    "IGDBAccessTokenProvider",
    "IGDBGameDTO",
    "IGDBGameResponse",
    "IGDBQuery",
    "IGDBQueryBuilder",
    "IGDBRateLimitError",
    "IGDBRequestError",
    "IGDBResponseFormat",
    "IGDBRetryConfig",
    "TwitchOAuthClient",
    "IGDBWrapperProtocol",
    "build_igdb_client",
]
