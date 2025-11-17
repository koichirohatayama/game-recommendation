"""Discord Webhook クライアントの挙動を検証する。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from game_recommendation.core.similarity.dto import (
    EmbeddedGameContext,
    SimilarityMatch,
    SimilarityQuery,
    SimilarityResult,
)
from game_recommendation.infra.discord import (
    DiscordRetryConfig,
    DiscordWebhookClient,
    DiscordWebhookError,
    DiscordWebhookRequest,
    build_recommendation_messages,
    chunk_message,
    notify_similarity_result,
)
from game_recommendation.shared.config import (
    AppSettings,
    DiscordSettings,
    GeminiSettings,
    IGDBSettings,
    StorageSettings,
)


def _http_status_error(status: int, url: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", url)
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_send_success() -> None:
    calls: list[dict[str, Any]] = []

    def http_post(url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        calls.append({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(204, request=httpx.Request("POST", url))

    client = DiscordWebhookClient(
        webhook_url="https://example.com/webhook",
        default_username="bot",
        http_post=http_post,
    )

    client.send(DiscordWebhookRequest(content="hello"))

    assert calls[0]["json"]["content"] == "hello"
    assert calls[0]["json"]["username"] == "bot"


def test_send_retries_and_succeeds() -> None:
    url = "https://example.com/webhook"
    state = {"attempt": 0}
    sleeps: list[float] = []

    def http_post(_url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        state["attempt"] += 1
        if state["attempt"] == 1:
            raise _http_status_error(429, url)
        return httpx.Response(204, request=httpx.Request("POST", _url))

    client = DiscordWebhookClient(
        webhook_url=url,
        default_username="bot",
        retry_config=DiscordRetryConfig(max_attempts=2, backoff_factor=0.1),
        http_post=http_post,
        sleep_func=sleeps.append,
    )

    client.send(DiscordWebhookRequest(content="ok"))

    assert sleeps == [0.1]
    assert state["attempt"] == 2


def test_send_raises_after_retries_exhausted() -> None:
    url = "https://example.com/webhook"
    sleeps: list[float] = []

    def http_post(_url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        raise _http_status_error(500, url)

    client = DiscordWebhookClient(
        webhook_url=url,
        retry_config=DiscordRetryConfig(max_attempts=2, backoff_factor=0.0),
        http_post=http_post,
        sleep_func=sleeps.append,
    )

    with pytest.raises(DiscordWebhookError):
        client.send(DiscordWebhookRequest(content="fail"))

    assert len(sleeps) == 1


def test_chunk_message_splits_by_limit() -> None:
    content = "a" * 25

    chunks = chunk_message(content, limit=10)

    assert chunks == ("a" * 10, "a" * 10, "a" * 5)


def test_build_recommendation_messages_contains_scores() -> None:
    result = SimilarityResult(
        query=SimilarityQuery(
            title="Base Game",
            tags=("Action",),
            genres=("RPG",),
            focus_keywords=("coop",),
        ),
        matches=(
            SimilarityMatch(
                candidate=EmbeddedGameContext(
                    game_id="1",
                    title="Recommended Game",
                    summary="A" * 400,
                    tags=("Action", "Co-op"),
                    genres=("RPG",),
                ),
                score=0.91,
                base_score=0.75,
                distance=0.12,
                reasons=("tag overlap", "keyword match"),
            ),
        ),
        embedding_model="test-model",
        computed_at=datetime(2024, 1, 1),
    )

    messages = build_recommendation_messages(result, limit=200)

    assert messages
    combined = "\n".join(messages)
    assert "0.91" in combined
    assert "判定根拠" in combined


def test_notify_similarity_result_uses_client() -> None:
    sent_messages: list[str] = []

    class StubClient:
        def send_messages(self, messages, *, username=None):
            sent_messages.extend(messages)
            self.username = username

    settings = AppSettings(
        igdb=IGDBSettings(client_id="cid", client_secret=SecretStr("secret")),
        discord=DiscordSettings(
            webhook_url="https://example.com/webhook",
            webhook_username="bot",
        ),
        gemini=GeminiSettings(api_key=SecretStr("api"), model="embed"),
        storage=StorageSettings(sqlite_path="./dummy.db"),
    )
    result = SimilarityResult(
        query=SimilarityQuery(title="Base"),
        matches=(
            SimilarityMatch(
                candidate=EmbeddedGameContext(game_id="1", title="A"),
                score=0.5,
                base_score=0.4,
                distance=0.3,
            ),
        ),
        embedding_model="test",
    )

    notify_similarity_result(result, settings=settings, client=StubClient())

    assert sent_messages
    assert "Base" in sent_messages[0]
