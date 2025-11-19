"""IGDB クライアントの基本的な挙動を検証する。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from igdb.igdbapi_pb2 import GameResult
from requests import HTTPError, Response

from game_recommendation.infra.igdb import (
    IGDBAccessToken,
    IGDBClient,
    IGDBQueryBuilder,
    IGDBRateLimitError,
    IGDBRequestError,
    IGDBResponseFormat,
    IGDBRetryConfig,
)
from game_recommendation.infra.igdb.client import _TAG_ENDPOINTS


class StubWrapper:
    """IGDBWrapper の呼び出しをスタブ化する。"""

    def __init__(self, actions: list[Any]) -> None:
        self._actions = list(actions)
        self.calls: list[tuple[str, str]] = []

    def api_request(self, endpoint: str, query: str) -> bytes:
        self.calls.append((endpoint, query))
        if not self._actions:
            msg = "No action registered"
            raise RuntimeError(msg)
        action = self._actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _http_error(status: int) -> HTTPError:
    response = Response()
    response.status_code = status
    return HTTPError(response=response)


def _build_client(actions: list[Any], **kwargs: Any) -> IGDBClient:
    class StubTokenProvider:
        def __init__(self, token: str = "token") -> None:
            self.token = token

        def get_token(self) -> IGDBAccessToken:
            return IGDBAccessToken(access_token=self.token, expires_at=None)

    token_provider = kwargs.pop("token_provider", StubTokenProvider())
    return IGDBClient(
        client_id="cid",
        token_provider=token_provider,
        wrapper_factory=lambda *_: StubWrapper(actions),
        **kwargs,
    )


def test_fetch_games_json() -> None:
    payload = json.dumps(
        [
            {
                "id": 101,
                "name": "Sample Game",
                "slug": "sample-game",
                "summary": "This is a sample",
                "first_release_date": 1_700_000_000,
                "cover": {"image_id": "abc123"},
                "platforms": [48, {"id": 130}],
                "tags": [10, "11"],
            }
        ]
    ).encode()

    query = (
        IGDBQueryBuilder()
        .select("id", "name", "cover.image_id")
        .where("first_release_date != null")
        .sort("first_release_date", "desc")
        .limit(10)
        .build()
    )
    client = _build_client([payload])

    response = client.fetch_games(query)

    assert response.format is IGDBResponseFormat.JSON
    assert len(response.items) == 1
    game = response.items[0]
    assert game.id == 101
    assert game.cover_image_id == "abc123"
    assert game.platforms == (48, 130)
    assert game.tags == (10, 11)

    endpoint, compiled_query = client._wrapper.calls[0]  # type: ignore[attr-defined]
    assert endpoint == "games"
    assert "fields id, name, cover.image_id;" in compiled_query
    assert "where first_release_date != null;" in compiled_query
    assert "sort first_release_date desc;" in compiled_query
    assert "limit 10;" in compiled_query


def test_fetch_games_protobuf() -> None:
    result = GameResult()
    game = result.games.add()
    game.id = 555
    game.name = "Proto Game"
    game.slug = "proto-game"
    game.summary = "proto summary"
    ts = Timestamp()
    ts.FromSeconds(1_700_000_000)
    game.first_release_date.CopyFrom(ts)
    game.cover.image_id = "proto-cover"
    platform = game.platforms.add()
    platform.id = 99
    game.tags.append(77)
    payload = result.SerializeToString()

    client = _build_client([payload])
    query = IGDBQueryBuilder().select("id", "name").build()

    response = client.fetch_games(query, response_format=IGDBResponseFormat.PROTOBUF)

    game = response.items[0]
    assert game.id == 555
    assert game.cover_image_id == "proto-cover"
    assert game.platforms == (99,)
    assert game.first_release_date == datetime.fromtimestamp(
        1_700_000_000,
        tz=UTC,
    )
    assert game.tags == (77,)

    endpoint, _ = client._wrapper.calls[0]  # type: ignore[attr-defined]
    assert endpoint == "games.pb"


def test_fetch_games_retry_then_success() -> None:
    sleep_calls: list[float] = []
    client = _build_client(
        [
            _http_error(429),
            _http_error(500),
            json.dumps([{"id": 1, "name": "ok"}]).encode(),
        ],
        retry_config=IGDBRetryConfig(max_attempts=3, backoff_factor=0.1),
        sleep_func=sleep_calls.append,
    )
    query = IGDBQueryBuilder().select("id").build()

    response = client.fetch_games(query)

    assert response.items[0].id == 1
    assert len(sleep_calls) == 2


def test_fetch_games_rate_limit_failure() -> None:
    client = _build_client(
        [_http_error(429), _http_error(429)],
        retry_config=IGDBRetryConfig(max_attempts=2, backoff_factor=0.0),
        sleep_func=lambda _duration: None,
    )
    query = IGDBQueryBuilder().select("id").build()

    with pytest.raises(IGDBRateLimitError):
        client.fetch_games(query)


def test_fetch_games_non_retriable_error() -> None:
    client = _build_client(
        [_http_error(404)],
        retry_config=IGDBRetryConfig(max_attempts=1),
        sleep_func=lambda _duration: None,
    )
    query = IGDBQueryBuilder().select("id").build()

    with pytest.raises(IGDBRequestError):
        client.fetch_games(query)


@pytest.mark.parametrize(
    "tag_class, endpoint",
    [
        ("genre", "genres"),
        ("keyword", "keywords"),
        ("theme", "themes"),
        ("player_perspective", "player_perspectives"),
        ("franchise", "franchises"),
        ("collection", "collections"),
    ],
)
def test_fetch_tags_endpoint_selection(tag_class: str, endpoint: str) -> None:
    payload = json.dumps([{"id": 1, "name": "test"}]).encode()
    client = _build_client([payload])

    result = client.fetch_tags(tag_class=tag_class, igdb_ids=[1])

    assert len(result) == 1
    called_endpoint, _ = client._wrapper.calls[0]  # type: ignore[attr-defined]
    assert called_endpoint == endpoint
    # 確認: マッピング定義に存在すること
    assert _TAG_ENDPOINTS[tag_class] == endpoint
