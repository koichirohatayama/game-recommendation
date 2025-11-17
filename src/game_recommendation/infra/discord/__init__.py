"""Discord Webhook 通知クライアント。"""

from .client import (
    DiscordRetryConfig,
    DiscordWebhookClient,
    DiscordWebhookError,
    DiscordWebhookRequest,
    notify_similarity_result,
)
from .templates import build_recommendation_messages, chunk_message, truncate_text

__all__ = [
    "DiscordRetryConfig",
    "DiscordWebhookClient",
    "DiscordWebhookError",
    "DiscordWebhookRequest",
    "notify_similarity_result",
    "build_recommendation_messages",
    "chunk_message",
    "truncate_text",
]
