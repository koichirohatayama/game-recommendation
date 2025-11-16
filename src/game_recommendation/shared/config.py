"""アプリケーション全体で共有する設定ローダー。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import ConfigurationError

EnvName = Literal["local", "test", "staging", "production"]


class IGDBSettings(BaseModel):
    """IGDB API 関連の資格情報。"""

    client_id: str = Field(..., description="IGDB API client id")
    client_secret: SecretStr = Field(..., description="IGDB API client secret")
    token_url: AnyHttpUrl = Field(
        "https://id.twitch.tv/oauth2/token", description="Twitch OAuth2 token endpoint"
    )
    refresh_margin_seconds: int = Field(
        300,
        ge=0,
        description="アクセストークン有効期限のこの秒数前になったら再取得する",
    )


class DiscordSettings(BaseModel):
    """Discord Webhook を利用した通知設定。"""

    webhook_url: AnyHttpUrl = Field(..., description="Discord Webhook URL")
    webhook_username: str = Field("GameReco Bot", description="Webhook 投稿時のユーザー名")


class GeminiSettings(BaseModel):
    """Gemini(API) 利用時の設定。"""

    api_key: SecretStr = Field(..., description="Google API key for Gemini")
    model: str = Field("embedding-001", description="利用するモデル名")


class StorageSettings(BaseModel):
    """データ保存関連の設定。"""

    sqlite_path: Path = Field(Path("./var/game_recommendation.db"), description="SQLite DB のパス")


class AppSettings(BaseSettings):
    """共有設定。`.env` 読み込みと環境変数バリデーションを担う。"""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    environment: EnvName = Field("local", description="実行環境識別子")
    log_level: str = Field("INFO", description="ルートロガーのログレベル")
    igdb: IGDBSettings
    discord: DiscordSettings
    gemini: GeminiSettings
    storage: StorageSettings = Field(default_factory=StorageSettings)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """設定をロードし、再利用する。

    LRU キャッシュによりプロセス内での重複読み込みを防ぎ、
    `pytest` などから `get_settings.cache_clear()` を呼び出すことで再読込できる。
    """

    try:
        return AppSettings()
    except ValidationError as exc:  # pragma: no cover - ValidationError carries context
        raise ConfigurationError(str(exc)) from exc


__all__ = [
    "AppSettings",
    "DiscordSettings",
    "GeminiSettings",
    "IGDBSettings",
    "StorageSettings",
    "EnvName",
    "get_settings",
]
