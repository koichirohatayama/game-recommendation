"""埋め込みサービスの公開ヘルパー。"""

from __future__ import annotations

import os
from collections.abc import Callable

from game_recommendation.shared.config import AppSettings, get_settings

from .base import EmbeddingServiceProtocol

EmbeddingServiceFactory = Callable[[AppSettings | None], EmbeddingServiceProtocol]

_REGISTRY: dict[str, EmbeddingServiceFactory] = {}


def register_embedding_service(name: str, factory: EmbeddingServiceFactory) -> None:
    """埋め込みサービスのファクトリを登録する。"""

    normalized = name.lower()
    _REGISTRY[normalized] = factory


def list_embedding_services() -> list[str]:
    """登録済みサービス名の一覧。"""

    return sorted(_REGISTRY)


def get_embedding_service(
    name: str,
    settings: AppSettings | None = None,
) -> EmbeddingServiceProtocol:
    """指定名の埋め込みサービスを取得する。"""

    normalized = name.lower()
    if normalized not in _REGISTRY:
        msg = f"Embedding service '{name}' is not registered"
        raise KeyError(msg)
    app_settings = settings or get_settings()
    return _REGISTRY[normalized](app_settings)


def get_default_embedding_service(settings: AppSettings | None = None) -> EmbeddingServiceProtocol:
    """環境変数 `EMBEDDING_PROVIDER` を参照してサービスを決定。"""

    provider_name = os.getenv("EMBEDDING_PROVIDER", "gemini")
    return get_embedding_service(provider_name, settings)


__all__ = [
    "EmbeddingServiceProtocol",
    "EmbeddingServiceFactory",
    "register_embedding_service",
    "get_embedding_service",
    "get_default_embedding_service",
    "list_embedding_services",
]


def _ensure_default_services() -> None:
    from . import gemini  # noqa: F401


_ensure_default_services()
