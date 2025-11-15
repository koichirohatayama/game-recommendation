"""共有型・ユーティリティ。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from typing import Any, NewType

UserID = NewType("UserID", str)
GameID = NewType("GameID", int)
Timestamp = datetime


@dataclass(slots=True)
class ValueObject:
    """DTO や VO のベースクラス。"""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DTO(ValueObject):
    """データ転送オブジェクト用ベース。"""


def dto_dict(instance: Any) -> dict[str, Any]:
    """DTO/VO、または任意の dataclass を dict 化する。"""

    if isinstance(instance, ValueObject):
        return instance.to_dict()
    if is_dataclass(instance):
        return asdict(instance)
    msg = "dto_dict expects a dataclass or ValueObject instance"
    raise TypeError(msg)


def utc_now() -> datetime:
    """UTC の現在時刻を返す。"""

    return datetime.now(UTC)


__all__ = [
    "ValueObject",
    "DTO",
    "dto_dict",
    "utc_now",
    "UserID",
    "GameID",
    "Timestamp",
]
