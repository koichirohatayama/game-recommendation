"""DB 向けインフラ。"""

from .models import Base, GameEmbedding, GameTag, GameTagLink, IgdbGame, UserFavoriteGame
from .session import DatabaseError, DatabaseSessionManager
from .sqlite_vec import (
    EmbeddingRepository,
    GameEmbeddingPayload,
    GameEmbeddingRecord,
    GameEmbeddingSearchResult,
    SQLiteVecConnectionManager,
    SQLiteVecEmbeddingRepository,
    SQLiteVecError,
    seed_embeddings,
)

__all__ = [
    "Base",
    "DatabaseError",
    "DatabaseSessionManager",
    "EmbeddingRepository",
    "GameEmbedding",
    "GameEmbeddingPayload",
    "GameEmbeddingRecord",
    "GameEmbeddingSearchResult",
    "GameTag",
    "GameTagLink",
    "IgdbGame",
    "SQLiteVecConnectionManager",
    "SQLiteVecEmbeddingRepository",
    "SQLiteVecError",
    "UserFavoriteGame",
    "seed_embeddings",
]
