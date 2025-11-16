"""IGDB取り込み用のドメインモデル。"""

from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)

__all__ = [
    "EmbeddedGamePayload",
    "GameTagPayload",
    "IngestedEmbedding",
]
