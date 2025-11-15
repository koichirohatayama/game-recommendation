"""IGDB API 向け infra 層パッケージ。"""

from .client import (
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
    build_igdb_client,
)
from .dto import IGDBGameDTO, IGDBGameResponse

__all__ = [
    "IGDBClient",
    "IGDBClientError",
    "IGDBClientProtocol",
    "IGDBGameDTO",
    "IGDBGameResponse",
    "IGDBQuery",
    "IGDBQueryBuilder",
    "IGDBRateLimitError",
    "IGDBRequestError",
    "IGDBResponseFormat",
    "IGDBRetryConfig",
    "IGDBWrapperProtocol",
    "build_igdb_client",
]
