"""shared.config の基本的な失敗ケースを確認するテスト。"""

from __future__ import annotations

import pytest

from game_recommendation.shared.config import get_settings
from game_recommendation.shared.exceptions import ConfigurationError

REQUIRED_KEYS = (
    "IGDB__CLIENT_ID",
    "IGDB__CLIENT_SECRET",
    "DISCORD__WEBHOOK_URL",
    "GEMINI__API_KEY",
    "GEMINI__MODEL",
)


@pytest.fixture(autouse=True)
def _cleanup_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_fail_when_env_missing(monkeypatch, tmp_path) -> None:
    """必須環境変数が欠けている場合 ConfigurationError が発生する。"""

    monkeypatch.chdir(tmp_path)
    for key in REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigurationError):
        get_settings()


def test_settings_load_from_nested_env(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "IGDB__CLIENT_ID": "cid",
        "IGDB__CLIENT_SECRET": "secret",
        "DISCORD__WEBHOOK_URL": "https://example.com/webhook",
        "DISCORD__WEBHOOK_USERNAME": "GameReco",
        "GEMINI__API_KEY": "gkey",
        "GEMINI__MODEL": "embed-002",
        "STORAGE__SQLITE_PATH": "./db.sqlite",
    }.items():
        monkeypatch.setenv(key, value)

    settings = get_settings()

    assert settings.igdb.client_id == "cid"
    assert settings.igdb.client_secret.get_secret_value() == "secret"
    assert str(settings.igdb.token_url) == "https://id.twitch.tv/oauth2/token"
    assert settings.igdb.refresh_margin_seconds == 300
    assert str(settings.discord.webhook_url) == "https://example.com/webhook"
    assert settings.discord.webhook_username == "GameReco"
    assert settings.gemini.api_key.get_secret_value() == "gkey"
    assert settings.gemini.model == "embed-002"
    assert str(settings.storage.sqlite_path) == "db.sqlite"


def test_settings_override_token_config(monkeypatch, tmp_path) -> None:
    """トークンエンドポイントとリフレッシュ猶予を環境変数で上書きできる。"""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IGDB__CLIENT_ID", "cid")
    monkeypatch.setenv("IGDB__CLIENT_SECRET", "secret")
    monkeypatch.setenv("IGDB__TOKEN_URL", "https://auth.example.com/token")
    monkeypatch.setenv("IGDB__REFRESH_MARGIN_SECONDS", "30")
    monkeypatch.setenv("DISCORD__WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("GEMINI__API_KEY", "gkey")
    monkeypatch.setenv("GEMINI__MODEL", "embed-002")

    settings = get_settings()

    assert str(settings.igdb.token_url) == "https://auth.example.com/token"
    assert settings.igdb.refresh_margin_seconds == 30
