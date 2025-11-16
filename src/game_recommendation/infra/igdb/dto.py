"""IGDB API 向け DTO およびレスポンス整形ユーティリティ。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from game_recommendation.shared.types import DTO


class IGDBResponseFormat(Enum):
    """IGDB API が返すレスポンス形式。"""

    JSON = "json"
    PROTOBUF = "protobuf"

    @property
    def endpoint_suffix(self) -> str:
        """IGDB API のエンドポイントへ付与するサフィックス。"""

        return ".pb" if self is IGDBResponseFormat.PROTOBUF else ""


@dataclass(slots=True)
class IGDBGameDTO(DTO):
    """ゲームの主要フィールドのみを保持する DTO。"""

    id: int
    name: str
    slug: str | None = None
    summary: str | None = None
    first_release_date: datetime | None = None
    cover_image_id: str | None = None
    platforms: tuple[int, ...] = ()
    category: int | None = None
    tags: tuple[int, ...] = ()


@dataclass(slots=True)
class IGDBTagDTO(DTO):
    """ジャンル/キーワードなどタグ情報の DTO。"""

    id: int
    name: str
    slug: str | None = None
    tag_class: str | None = None


@dataclass(slots=True)
class IGDBGameResponse(DTO):
    """ゲームリストのレスポンス。"""

    items: tuple[IGDBGameDTO, ...]
    raw: bytes
    format: IGDBResponseFormat


def parse_games_from_payload(payload: bytes, fmt: IGDBResponseFormat) -> tuple[IGDBGameDTO, ...]:
    """レスポンスバイト列を DTO 群へ変換する。"""

    if not payload:
        return ()

    if fmt is IGDBResponseFormat.JSON:
        return _parse_games_from_json(payload)
    return _parse_games_from_proto(payload)


def _parse_games_from_json(payload: bytes) -> tuple[IGDBGameDTO, ...]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # noqa: PERF203 - 明確な例外
        raise ValueError("Invalid JSON payload for IGDB response") from exc

    if not isinstance(decoded, list):
        raise ValueError("IGDB JSON payload must be an array")

    games: list[IGDBGameDTO] = []
    for raw_game in decoded:
        if not isinstance(raw_game, dict):
            msg = "Each game record must be an object"
            raise ValueError(msg)
        games.append(_map_game_dict(raw_game))

    return tuple(games)


def _parse_games_from_proto(payload: bytes) -> tuple[IGDBGameDTO, ...]:
    try:
        from igdb.igdbapi_pb2 import GameResult
    except ImportError as exc:  # pragma: no cover - import 時の例外
        raise RuntimeError("igdb-api-python is not installed") from exc

    message = GameResult()
    message.ParseFromString(payload)
    return tuple(_map_game_message(game) for game in message.games)


def _map_game_dict(data: dict[str, Any]) -> IGDBGameDTO:
    game_id = data.get("id")
    name = data.get("name")
    if not isinstance(game_id, int) or not isinstance(name, str):
        msg = "Game record must contain `id` (int) and `name` (str)"
        raise ValueError(msg)

    first_release_date = _timestamp_to_datetime(data.get("first_release_date"))
    slug = data.get("slug") if isinstance(data.get("slug"), str) else None
    summary = data.get("summary") if isinstance(data.get("summary"), str) else None
    cover_obj = data.get("cover") if isinstance(data.get("cover"), dict) else None
    cover_image_id = cover_obj.get("image_id") if isinstance(cover_obj, dict) else None
    platforms = _coerce_platforms(data.get("platforms"))
    category = data.get("category") if isinstance(data.get("category"), int) else None
    tags = _coerce_int_tuple(data.get("tags"))

    return IGDBGameDTO(
        id=game_id,
        name=name,
        slug=slug,
        summary=summary,
        first_release_date=first_release_date,
        cover_image_id=cover_image_id if isinstance(cover_image_id, str) else None,
        platforms=platforms,
        category=category,
        tags=tags,
    )


def _map_game_message(message: Any) -> IGDBGameDTO:
    game_id = int(message.id)
    name = str(message.name)
    slug = str(message.slug) if getattr(message, "slug", "") else None
    summary = str(message.summary) if getattr(message, "summary", "") else None
    ts = int(getattr(message.first_release_date, "seconds", 0) or 0)
    cover_image_id = None
    if getattr(message, "cover", None) is not None and message.HasField("cover"):
        if getattr(message.cover, "image_id", ""):
            cover_image_id = str(message.cover.image_id)

    platforms = _coerce_platforms(message.platforms)
    category = (
        int(message.category) if getattr(message, "category", None) not in (None, "") else None
    )
    tags = tuple(int(tag) for tag in getattr(message, "tags", []))

    return IGDBGameDTO(
        id=game_id,
        name=name,
        slug=slug,
        summary=summary,
        first_release_date=_timestamp_to_datetime(ts),
        cover_image_id=cover_image_id,
        platforms=platforms,
        category=category,
        tags=tags,
    )


def _timestamp_to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)  # noqa: UP017 - Py311 fallback


def _coerce_platforms(raw: Any) -> tuple[int, ...]:
    if not raw:
        return ()

    result: list[int] = []
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        iterable = raw
    else:
        iterable = (raw,)

    for platform in iterable:
        if isinstance(platform, int):
            result.append(platform)
        elif isinstance(platform, dict):
            value = platform.get("id")
            if isinstance(value, int):
                result.append(value)
        else:
            value = getattr(platform, "id", None)
            if isinstance(value, int):
                result.append(value)

    return tuple(result)


def _coerce_int_tuple(raw: Any) -> tuple[int, ...]:
    if not raw:
        return ()

    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        values = (raw,)

    ints: list[int] = []
    for value in values:
        if isinstance(value, int):
            ints.append(value)
            continue
        try:
            ints.append(int(value))
        except (TypeError, ValueError):
            continue

    return tuple(ints)


def parse_tags_from_payload(payload: bytes) -> tuple[IGDBTagDTO, ...]:
    """タグ系エンドポイントのレスポンスを DTO に変換する。"""

    if not payload:
        return ()

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # noqa: PERF203 - 明確な例外
        raise ValueError("Invalid JSON payload for IGDB tags") from exc

    if not isinstance(decoded, list):
        raise ValueError("IGDB tag payload must be an array")

    tags: list[IGDBTagDTO] = []
    for raw_tag in decoded:
        if not isinstance(raw_tag, dict):
            raise ValueError("Each tag record must be an object")
        tag_id = raw_tag.get("id")
        name = raw_tag.get("name")
        if not isinstance(tag_id, int) or not isinstance(name, str):
            raise ValueError("Tag record must contain `id` (int) and `name` (str)")
        slug = raw_tag.get("slug") if isinstance(raw_tag.get("slug"), str) else None
        tags.append(IGDBTagDTO(id=tag_id, name=name, slug=slug))

    return tuple(tags)


__all__ = [
    "IGDBGameDTO",
    "IGDBGameResponse",
    "IGDBResponseFormat",
    "IGDBTagDTO",
    "parse_games_from_payload",
    "parse_tags_from_payload",
]
