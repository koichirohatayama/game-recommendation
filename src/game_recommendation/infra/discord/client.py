"""Discord Webhook へ推薦結果を送信するクライアント。"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from game_recommendation.core.similarity.dto import SimilarityResult
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger

from .templates import DISCORD_MESSAGE_LIMIT, build_recommendation_messages


class DiscordWebhookError(BaseAppError):
    """Webhook 投稿に失敗した際の例外。"""


@dataclass(slots=True)
class DiscordWebhookRequest:
    """Webhook へ送信するリクエスト DTO。"""

    content: str
    username: str | None = None


@dataclass(slots=True)
class DiscordRetryConfig:
    """リトライ設定。"""

    max_attempts: int = 3
    backoff_factor: float = 0.5
    retriable_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


class DiscordWebhookClient:
    """Discord Webhook へメッセージを送信するクライアント。"""

    def __init__(
        self,
        *,
        webhook_url: str,
        default_username: str | None = None,
        retry_config: DiscordRetryConfig | None = None,
        http_post: Callable[..., httpx.Response] = httpx.post,
        timeout: float = 10.0,
        logger=None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._webhook_url = webhook_url
        self._default_username = default_username
        self._retry_config = retry_config or DiscordRetryConfig()
        self._http_post = http_post
        self._timeout = timeout
        self._sleep = sleep_func
        self._logger = logger or get_logger(__name__)

    def send(self, request: DiscordWebhookRequest) -> None:
        """単一メッセージを送信する。"""

        payload = {"content": request.content}
        username = request.username or self._default_username
        if username:
            payload["username"] = username

        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http_post(
                    self._webhook_url,
                    json=payload,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if not self._should_retry(status_code, attempt):
                    body = exc.response.text if exc.response is not None else None
                    self._logger.error(
                        "discord_webhook_failed",
                        status_code=status_code,
                        attempt=attempt,
                        body=body.strip() if body else None,
                    )
                    msg = "Discord Webhook 送信に失敗しました"
                    raise DiscordWebhookError(msg) from exc

                self._logger.warning(
                    "discord_webhook_retry",
                    status_code=status_code,
                    attempt=attempt,
                )
                self._sleep(self._retry_config.backoff_factor * attempt)
            except httpx.RequestError as exc:
                if not self._should_retry(None, attempt):
                    self._logger.error(
                        "discord_webhook_request_error",
                        attempt=attempt,
                        message=str(exc),
                    )
                    msg = "Discord Webhook 通信に失敗しました"
                    raise DiscordWebhookError(msg) from exc

                self._logger.warning(
                    "discord_webhook_retry",
                    status_code=None,
                    attempt=attempt,
                )
                self._sleep(self._retry_config.backoff_factor * attempt)

    def send_messages(self, messages: Sequence[str], *, username: str | None = None) -> None:
        """複数メッセージを順次送信する。"""

        for content in messages:
            self.send(DiscordWebhookRequest(content=content, username=username))

    def _should_retry(self, status_code: int | None, attempt: int) -> bool:
        if attempt >= self._retry_config.max_attempts:
            return False
        if status_code is None:
            return True
        return status_code in self._retry_config.retriable_statuses


def notify_similarity_result(
    result: SimilarityResult,
    *,
    settings: AppSettings | None = None,
    client: DiscordWebhookClient | None = None,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> None:
    """類似度判定結果を Webhook へ通知する。"""

    app_settings = settings or get_settings()
    discord_settings = app_settings.discord
    webhook_client = client or DiscordWebhookClient(
        webhook_url=str(discord_settings.webhook_url),
        default_username=discord_settings.webhook_username,
    )

    messages = build_recommendation_messages(result, limit=message_limit)
    if not messages:
        return

    webhook_client.send_messages(messages, username=discord_settings.webhook_username)


__all__ = [
    "DiscordRetryConfig",
    "DiscordWebhookClient",
    "DiscordWebhookError",
    "DiscordWebhookRequest",
    "notify_similarity_result",
]
