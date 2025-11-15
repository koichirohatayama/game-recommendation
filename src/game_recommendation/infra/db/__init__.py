"""DB 向けインフラ。"""

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
    "EmbeddingRepository",
    "GameEmbeddingPayload",
    "GameEmbeddingRecord",
    "GameEmbeddingSearchResult",
    "SQLiteVecConnectionManager",
    "SQLiteVecEmbeddingRepository",
    "SQLiteVecError",
    "seed_embeddings",
]
