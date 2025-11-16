"""SQLAlchemy エンジンとセッションの管理。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger

BoundLogger = structlog.stdlib.BoundLogger


class DatabaseError(BaseAppError):
    """DB 管理に関する例外。"""


class DatabaseSessionManager:
    """SQLAlchemy エンジン・セッション、および Alembic 実行を担うユーティリティ。"""

    _ALEMBIC_CONFIG = Path(__file__).resolve().parents[4] / "alembic.ini"
    _ALEMBIC_SCRIPT_DIR = Path(__file__).parent / "alembic"

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        settings: AppSettings | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        resolved_path = db_path or self._settings.storage.sqlite_path
        self._db_path = Path(resolved_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._logger = logger or get_logger(__name__, component="db")
        self._engine = self._create_engine()
        self._session_factory = sessionmaker(
            self._engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

    @property
    def url(self) -> str:
        return str(URL.create("sqlite", database=str(self._db_path)))

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._session_factory() as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._session_factory.begin() as session:
            yield session

    def initialize_schema(self, revision: str = "head") -> None:
        """Alembic でスキーマを最新化する。"""

        if not self._ALEMBIC_CONFIG.exists():
            msg = f"Alembic config not found: {self._ALEMBIC_CONFIG}"
            raise DatabaseError(msg)

        config = Config(str(self._ALEMBIC_CONFIG))
        config.set_main_option("script_location", str(self._ALEMBIC_SCRIPT_DIR))
        config.set_main_option("sqlalchemy.url", self.url)
        command.upgrade(config, revision)

    def close(self) -> None:
        self._engine.dispose()

    def _create_engine(self) -> Engine:
        engine = create_engine(self.url, future=True)
        event.listen(engine, "connect", self._on_connect)
        return engine

    def _on_connect(
        self,
        dbapi_conn: sqlite3.Connection,
        _,
    ) -> None:  # pragma: no cover - DBAPI hook
        dbapi_conn.execute("PRAGMA foreign_keys = ON;")
