"""共通例外と結果型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


class BaseAppError(Exception):
    """全レイヤで共有するベース例外。"""

    default_message = "An unexpected error occurred"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class ConfigurationError(BaseAppError):
    """設定読み込みや不足を示すエラー。"""

    default_message = "Configuration is invalid or missing"


class DomainError(BaseAppError):
    """ドメイン層で利用する基底例外。"""

    default_message = "Domain layer error"


T = TypeVar("T")
E = TypeVar("E", bound=BaseAppError)


@dataclass(slots=True)
class Result(Generic[T, E]):
    """成功/失敗を同一インターフェースで扱う結果型。"""

    value: T | None = None
    error: E | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.error is None):
            msg = "Result must contain either value or error"
            raise ValueError(msg)

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def is_err(self) -> bool:
        return self.error is not None

    def unwrap(self) -> T:
        if self.value is None:
            msg = "Cannot unwrap error result"
            raise RuntimeError(msg)
        return self.value

    def unwrap_err(self) -> E:
        if self.error is None:
            msg = "Cannot unwrap ok result"
            raise RuntimeError(msg)
        return self.error

    @classmethod
    def ok(cls, value: T) -> Result[T, E]:
        return cls(value=value)

    @classmethod
    def err(cls, error: E) -> Result[T, E]:
        return cls(error=error)


__all__ = [
    "BaseAppError",
    "ConfigurationError",
    "DomainError",
    "Result",
]
