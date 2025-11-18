"""DB 向けインフラ。"""

from .embedding_repository import (
    EmbeddingRepository,
    EmbeddingRepositoryError,
    GameEmbeddingPayload,
    GameEmbeddingRecord,
    GameEmbeddingSearchResult,
    SQLAlchemyEmbeddingRepository,
    seed_embeddings,
)
from .models import (
    Base,
    GameEmbedding,
    GameTag,
    GameTagLink,
    IgdbGame,
    UserFavoriteGame,
)
from .session import DatabaseError, DatabaseSessionManager
from .tag_repository import SQLAlchemyGameTagRepository

__all__ = [
    "Base",
    "DatabaseError",
    "DatabaseSessionManager",
    "EmbeddingRepository",
    "EmbeddingRepositoryError",
    "GameEmbedding",
    "GameEmbeddingPayload",
    "GameEmbeddingRecord",
    "GameEmbeddingSearchResult",
    "GameTag",
    "GameTagLink",
    "IgdbGame",
    "SQLAlchemyEmbeddingRepository",
    "SQLAlchemyGameTagRepository",
    "UserFavoriteGame",
    "seed_embeddings",
]
