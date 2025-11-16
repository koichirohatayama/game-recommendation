"""インジェスト系ドメインモデルとサービス。"""

from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
    IngestedEmbedding,
)
from game_recommendation.core.ingest.tag_resolver import (
    GameTagRepositoryProtocol,
    ResolvedTag,
    TagClientProtocol,
    TagResolver,
    TagResolverError,
)

__all__ = [
    "EmbeddedGamePayload",
    "GameTagPayload",
    "IngestedEmbedding",
    "GameTagRepositoryProtocol",
    "ResolvedTag",
    "TagClientProtocol",
    "TagResolver",
    "TagResolverError",
]
