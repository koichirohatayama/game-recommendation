"""DB 向けインフラ。"""

from .models import Base, GameEmbedding, GameTag, GameTagLink, IgdbGame, UserFavoriteGame
from .repositories import SQLAlchemyGameTagRepository
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
    "SQLAlchemyGameTagRepository",
    "UserFavoriteGame",
    "seed_embeddings",
]
