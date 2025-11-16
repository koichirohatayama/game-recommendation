"""sqlite-vec を SQLAlchemy ベースで扱う埋め込み DAO。"""

from __future__ import annotations

import json
import math
import sqlite3
from abc import ABC, abstractmethod
from array import array
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, select, text
from sqlalchemy.engine import URL, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from game_recommendation.infra.db.models import GameEmbedding
from game_recommendation.shared.config import AppSettings, get_settings
from game_recommendation.shared.exceptions import BaseAppError
from game_recommendation.shared.logging import get_logger
from game_recommendation.shared.types import DTO

try:  # pragma: no cover - オプショナル依存の存在確認
    import sqlite_vec  # type: ignore
except ImportError:  # pragma: no cover
    sqlite_vec = None


BoundLogger = structlog.stdlib.BoundLogger
DistanceMetric = Literal["cosine", "l2"]


class SQLiteVecError(BaseAppError):
    """sqlite-vec に関するエラー。"""

    default_message = "SQLite-vec operation failed"


@dataclass(slots=True)
class GameEmbeddingPayload(DTO):
    """埋め込み保存時に利用する入力 DTO。"""

    game_id: str
    title_embedding: tuple[float, ...]
    description_embedding: tuple[float, ...]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "title_embedding",
            tuple(float(value) for value in self.title_embedding),
        )
        object.__setattr__(
            self,
            "description_embedding",
            tuple(float(value) for value in self.description_embedding),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(slots=True)
class GameEmbeddingRecord(DTO):
    """DB から取得した埋め込み DTO。"""

    game_id: str
    dimension: int
    title_embedding: tuple[float, ...]
    description_embedding: tuple[float, ...]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "title_embedding", tuple(self.title_embedding))
        object.__setattr__(self, "description_embedding", tuple(self.description_embedding))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(slots=True)
class GameEmbeddingSearchResult(GameEmbeddingRecord):
    """検索結果 DTO。"""

    distance: float


class EmbeddingRepository(ABC):
    """埋め込み DAO の抽象化。"""

    @abstractmethod
    def upsert_embedding(self, payload: GameEmbeddingPayload) -> GameEmbeddingRecord: ...

    @abstractmethod
    def get_embedding(self, game_id: str) -> GameEmbeddingRecord | None: ...

    @abstractmethod
    def search_similar(
        self,
        query_embedding: Sequence[float],
        *,
        limit: int = 10,
    ) -> list[GameEmbeddingSearchResult]: ...


class SQLiteVecConnectionManager:
    """SQLAlchemy エンジンを管理し、sqlite-vec 拡張のロードも担う。"""

    _ALEMBIC_CONFIG = Path(__file__).resolve().parents[4] / "alembic.ini"
    _ALEMBIC_SCRIPT_DIR = Path(__file__).parent / "alembic"

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        settings: AppSettings | None = None,
        load_extension: bool = True,
        extension_path: Path | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        resolved_path = db_path or self._settings.storage.sqlite_path
        self._db_path = Path(resolved_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._load_extension = load_extension
        self._extension_path = extension_path
        self._logger = logger or get_logger(__name__, component="sqlite-vec")

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
        """Alembic を使ってスキーマを最新化。"""

        if not self._ALEMBIC_CONFIG.exists():
            msg = f"Alembic config not found: {self._ALEMBIC_CONFIG}"
            raise SQLiteVecError(msg)

        config = Config(str(self._ALEMBIC_CONFIG))
        config.set_main_option("script_location", str(self._ALEMBIC_SCRIPT_DIR))
        config.set_main_option("sqlalchemy.url", self.url)
        command.upgrade(config, revision)

    def ensure_vec_index(self, *, table_name: str, column: str, dimension: int) -> bool:
        """vec0 仮想テーブルを生成し、利用可能かを返す。"""

        ddl = (
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} "
            f"USING vec0({column} FLOAT[{dimension}])"
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(text(ddl))
        except OperationalError as exc:
            self._logger.warning("sqlite_vec.vec_table_init_failed", error=str(exc))
            return False
        return True

    def close(self) -> None:
        self._engine.dispose()

    def _create_engine(self) -> Engine:
        engine = create_engine(self.url, future=True)
        event.listen(engine, "connect", self._on_connect)
        return engine

    def _on_connect(
        self, dbapi_conn: sqlite3.Connection, _
    ) -> None:  # pragma: no cover - DBAPI hook
        dbapi_conn.execute("PRAGMA foreign_keys = ON;")

        if not self._load_extension:
            return

        path = self._resolve_extension_path()
        if path is None:
            self._logger.warning("sqlite_vec.extension_missing")
            return

        try:
            dbapi_conn.enable_load_extension(True)
            dbapi_conn.load_extension(str(path))
        except sqlite3.OperationalError as exc:
            self._logger.warning("sqlite_vec.extension_load_failed", error=str(exc))
        else:
            self._logger.info("sqlite_vec.extension_loaded", path=str(path))
        finally:
            dbapi_conn.enable_load_extension(False)

    def _resolve_extension_path(self) -> Path | None:
        if self._extension_path is not None:
            return Path(self._extension_path)
        if sqlite_vec is None:
            return None
        return Path(sqlite_vec.loadable_path())  # type: ignore[func-returns-value]


class SQLiteVecEmbeddingRepository(EmbeddingRepository):
    """sqlite-vec を用いた埋め込み DAO。"""

    TABLE_NAME = "game_embeddings"
    VEC_TABLE_NAME = "game_embeddings_vec"

    def __init__(
        self,
        manager: SQLiteVecConnectionManager,
        *,
        dimension: int = 768,
        enable_vec_index: bool = True,
        distance_metric: DistanceMetric = "cosine",
        logger: BoundLogger | None = None,
    ) -> None:
        self._manager = manager
        self._dimension = dimension
        self._distance_metric = distance_metric
        self._logger = logger or get_logger(__name__, component="sqlite-vec-dao")
        self._vec_index_ready = False

        if enable_vec_index:
            self._vec_index_ready = self._manager.ensure_vec_index(
                table_name=self.VEC_TABLE_NAME,
                column="description_embedding",
                dimension=dimension,
            )

    def upsert_embedding(self, payload: GameEmbeddingPayload) -> GameEmbeddingRecord:
        title_vec = _normalize_embedding(payload.title_embedding)
        desc_vec = _normalize_embedding(payload.description_embedding)
        if len(title_vec) != self._dimension or len(desc_vec) != self._dimension:
            msg = "Embedding dimension mismatch"
            raise SQLiteVecError(msg)

        title_blob = _embedding_to_blob(title_vec)
        desc_blob = _embedding_to_blob(desc_vec)
        now = datetime.utcnow()

        with self._manager.transaction() as session:
            existing = session.execute(
                select(GameEmbedding).where(GameEmbedding.game_id == payload.game_id)
            ).scalar_one_or_none()

            if existing is None:
                model = GameEmbedding(
                    game_id=payload.game_id,
                    dimension=self._dimension,
                    title_embedding=title_blob,
                    description_embedding=desc_blob,
                    embedding_metadata=payload.metadata,
                    created_at=now,
                    updated_at=now,
                )
                session.add(model)
                session.flush()
            else:
                existing.dimension = self._dimension
                existing.title_embedding = title_blob
                existing.description_embedding = desc_blob
                existing.embedding_metadata = payload.metadata
                existing.updated_at = now
                model = existing
                session.flush()

            if self._vec_index_ready and model.id is not None:
                self._vec_index_ready = self._sync_vec_index(session, model.id, desc_vec)

            session.refresh(model)

        return self._model_to_record(model)

    def get_embedding(self, game_id: str) -> GameEmbeddingRecord | None:
        with self._manager.session() as session:
            model = session.execute(
                select(GameEmbedding).where(GameEmbedding.game_id == game_id)
            ).scalar_one_or_none()

        if model is None:
            return None
        return self._model_to_record(model)

    def search_similar(
        self,
        query_embedding: Sequence[float],
        *,
        limit: int = 10,
    ) -> list[GameEmbeddingSearchResult]:
        normalized = _normalize_embedding(query_embedding)
        if len(normalized) != self._dimension:
            msg = "Query embedding dimension mismatch"
            raise SQLiteVecError(msg)

        if self._vec_index_ready:
            try:
                return self._search_with_vec_index(normalized, limit)
            except OperationalError as exc:
                self._logger.warning("sqlite_vec.query_failed", error=str(exc))
                self._vec_index_ready = False

        return self._search_fallback(normalized, limit)

    def _search_with_vec_index(
        self,
        embedding: tuple[float, ...],
        limit: int,
    ) -> list[GameEmbeddingSearchResult]:
        query_vector = json.dumps(embedding)
        with self._manager.session() as session:
            rows = (
                session.execute(
                    text(
                        f"""
                        SELECT ge.game_id, ge.dimension,
                               ge.title_embedding, ge.description_embedding, ge.metadata,
                               ge.created_at, ge.updated_at, vec.distance
                        FROM {self.VEC_TABLE_NAME} AS vec
                        JOIN {self.TABLE_NAME} AS ge ON ge.id = vec.rowid
                        WHERE vec.description_embedding MATCH :query
                        ORDER BY vec.distance
                        LIMIT :limit
                        """
                    ),
                    {"query": query_vector, "limit": limit},
                )
                .mappings()
                .all()
            )

        return [self._row_to_search_result(row) for row in rows]

    def _search_fallback(
        self,
        embedding: tuple[float, ...],
        limit: int,
    ) -> list[GameEmbeddingSearchResult]:
        with self._manager.session() as session:
            models = (
                session.execute(
                    select(GameEmbedding).where(GameEmbedding.dimension == self._dimension)
                )
                .scalars()
                .all()
            )

        records = [self._model_to_record(model) for model in models]
        results: list[GameEmbeddingSearchResult] = []
        for record in records:
            distance = _calculate_distance(
                record.description_embedding,
                embedding,
                metric=self._distance_metric,
            )
            results.append(GameEmbeddingSearchResult(distance=distance, **record.to_dict()))

        results.sort(key=lambda item: item.distance)
        return results[:limit]

    def _sync_vec_index(
        self,
        session: Session,
        row_id: int,
        embedding: tuple[float, ...],
    ) -> bool:
        vector = json.dumps(embedding)
        try:
            session.execute(
                text(f"DELETE FROM {self.VEC_TABLE_NAME} WHERE rowid = :row_id"),
                {"row_id": row_id},
            )
            session.execute(
                text(
                    f"INSERT INTO {self.VEC_TABLE_NAME}(rowid, description_embedding) "
                    "VALUES (:row_id, :embedding)"
                ),
                {"row_id": row_id, "embedding": vector},
            )
        except OperationalError as exc:
            self._logger.warning("sqlite_vec.query_failed", error=str(exc))
            return False
        return True

    def _model_to_record(self, model: GameEmbedding) -> GameEmbeddingRecord:
        metadata = model.embedding_metadata or {}
        return GameEmbeddingRecord(
            game_id=model.game_id,
            dimension=model.dimension,
            title_embedding=_blob_to_embedding(model.title_embedding, model.dimension),
            description_embedding=_blob_to_embedding(model.description_embedding, model.dimension),
            metadata=metadata if isinstance(metadata, dict) else json.loads(str(metadata)),
            created_at=_coerce_datetime(model.created_at),
            updated_at=_coerce_datetime(model.updated_at),
        )

    def _row_to_search_result(self, row: Any) -> GameEmbeddingSearchResult:
        mapping = row if isinstance(row, dict) else row._mapping  # type: ignore[attr-defined]
        metadata = mapping.get("metadata") or {}
        title_blob = mapping["title_embedding"]
        desc_blob = mapping["description_embedding"]
        return GameEmbeddingSearchResult(
            game_id=mapping["game_id"],
            dimension=mapping["dimension"],
            title_embedding=_blob_to_embedding(title_blob, mapping["dimension"]),
            description_embedding=_blob_to_embedding(desc_blob, mapping["dimension"]),
            metadata=metadata if isinstance(metadata, dict) else json.loads(str(metadata)),
            created_at=_coerce_datetime(mapping["created_at"]),
            updated_at=_coerce_datetime(mapping["updated_at"]),
            distance=float(mapping["distance"]),
        )


def seed_embeddings(
    repo: EmbeddingRepository,
    entries: Iterable[GameEmbeddingPayload],
) -> list[GameEmbeddingRecord]:
    """テストやプロトタイプでまとめて埋め込みを投入するヘルパー。"""

    stored: list[GameEmbeddingRecord] = []
    for entry in entries:
        stored.append(repo.upsert_embedding(entry))
    return stored


def _normalize_embedding(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(float(value) for value in values)


def _embedding_to_blob(values: Sequence[float]) -> bytes:
    buf = array("f", values)
    return buf.tobytes()


def _blob_to_embedding(blob: bytes, dimension: int) -> tuple[float, ...]:
    buf = array("f")
    buf.frombytes(bytes(blob))
    if len(buf) != dimension:
        raise SQLiteVecError("Stored embedding dimension mismatch")
    return tuple(float(value) for value in buf)


def _calculate_distance(
    x: Sequence[float],
    y: Sequence[float],
    *,
    metric: DistanceMetric,
) -> float:
    if metric == "l2":
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(x, y, strict=True)))

    dot = sum(a * b for a, b in zip(x, y, strict=True))
    norm_x = math.sqrt(sum(a * a for a in x))
    norm_y = math.sqrt(sum(b * b for b in y))
    if norm_x == 0 or norm_y == 0:  # pragma: no cover - 無限大の扱いは想定外
        return float("inf")
    cosine_similarity = dot / (norm_x * norm_y)
    return 1 - cosine_similarity


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value))


__all__ = [
    "EmbeddingRepository",
    "GameEmbeddingPayload",
    "GameEmbeddingRecord",
    "GameEmbeddingSearchResult",
    "SQLiteVecConnectionManager",
    "SQLiteVecEmbeddingRepository",
    "SQLiteVecError",
    "seed_embeddings",
]
