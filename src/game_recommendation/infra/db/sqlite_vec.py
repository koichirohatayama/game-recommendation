"""sqlite-vec を利用した SQLite リポジトリの骨組み実装。"""

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
from threading import Lock
from typing import Any, Literal

import structlog

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
    embedding: tuple[float, ...]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "embedding",
            tuple(float(value) for value in self.embedding),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(slots=True)
class GameEmbeddingRecord(DTO):
    """DB から取得した埋め込み DTO。"""

    game_id: str
    dimension: int
    embedding: tuple[float, ...]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "embedding", tuple(self.embedding))
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
    """sqlite3 接続を管理し、vec 拡張のロードを担う。"""

    _MIGRATIONS_DIR = Path(__file__).with_name("migrations")

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
        self._lock = Lock()
        self._connection: sqlite3.Connection | None = None
        self._extension_loaded = False

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._ensure_connection()
        try:
            yield conn
        finally:
            pass

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._ensure_connection()
        try:
            yield conn
            conn.commit()
        except Exception:  # pragma: no cover - 例外伝搬を維持
            conn.rollback()
            raise

    def initialize_schema(self) -> None:
        """migrations ディレクトリにある SQL を順番に実行する。"""

        with self.connection() as conn:
            for script in self._iter_migrations():
                conn.executescript(script)
            conn.commit()

    def ensure_vec_index(self, *, table_name: str, column: str, dimension: int) -> bool:
        """vec0 仮想テーブルを生成し、利用可能かを返す。"""

        ddl = (
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} "
            f"USING vec0({column} FLOAT[{dimension}])"
        )
        try:
            with self.connection() as conn:
                conn.execute(ddl)
                conn.commit()
        except sqlite3.OperationalError as exc:
            self._logger.warning("sqlite_vec.vec_table_init_failed", error=str(exc))
            return False
        return True

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None

    def _ensure_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is not None:
                return self._connection

            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")

            if self._load_extension:
                self._extension_loaded = self._load_vec_extension(conn)

            self._connection = conn
            return conn

    def _iter_migrations(self) -> Iterator[str]:
        for sql_file in sorted(self._MIGRATIONS_DIR.glob("*.sql")):
            yield sql_file.read_text(encoding="utf-8")

    def _load_vec_extension(self, conn: sqlite3.Connection) -> bool:
        path = self._resolve_extension_path()
        if path is None:
            self._logger.warning("sqlite_vec.extension_missing")
            return False

        try:
            conn.enable_load_extension(True)
            conn.load_extension(str(path))
        except sqlite3.OperationalError as exc:
            self._logger.warning("sqlite_vec.extension_load_failed", error=str(exc))
            return False
        finally:
            conn.enable_load_extension(False)

        self._logger.info("sqlite_vec.extension_loaded", path=str(path))
        return True

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
        dimension: int,
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
                column="embedding",
                dimension=dimension,
            )

    def upsert_embedding(self, payload: GameEmbeddingPayload) -> GameEmbeddingRecord:
        normalized = _normalize_embedding(payload.embedding)
        if len(normalized) != self._dimension:
            msg = "Embedding dimension mismatch"
            raise SQLiteVecError(msg)

        blob = _embedding_to_blob(normalized)
        metadata_json = json.dumps(payload.metadata, ensure_ascii=False)

        with self._manager.transaction() as conn:
            conn.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} (game_id, dimension, embedding, metadata)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    dimension=excluded.dimension,
                    embedding=excluded.embedding,
                    metadata=excluded.metadata,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (payload.game_id, self._dimension, blob, metadata_json),
            )
            if self._vec_index_ready:
                self._sync_vec_index(conn, payload.game_id, normalized)

            row = conn.execute(
                f"""
                SELECT game_id, dimension, embedding, metadata, created_at, updated_at
                FROM {self.TABLE_NAME}
                WHERE game_id = ?
                """,
                (payload.game_id,),
            ).fetchone()

        return self._row_to_record(row)

    def get_embedding(self, game_id: str) -> GameEmbeddingRecord | None:
        with self._manager.connection() as conn:
            row = conn.execute(
                f"""
                SELECT game_id, dimension, embedding, metadata, created_at, updated_at
                FROM {self.TABLE_NAME}
                WHERE game_id = ?
                """,
                (game_id,),
            ).fetchone()

        if row is None:
            return None
        return self._row_to_record(row)

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
            except sqlite3.OperationalError as exc:
                self._logger.warning("sqlite_vec.query_failed", error=str(exc))
                self._vec_index_ready = False

        return self._search_fallback(normalized, limit)

    def _search_with_vec_index(
        self,
        embedding: tuple[float, ...],
        limit: int,
    ) -> list[GameEmbeddingSearchResult]:
        query_vector = json.dumps(embedding)
        with self._manager.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT ge.game_id, ge.dimension, ge.embedding, ge.metadata,
                       ge.created_at, ge.updated_at, vec.distance
                FROM {self.VEC_TABLE_NAME} AS vec
                JOIN {self.TABLE_NAME} AS ge ON ge.id = vec.rowid
                WHERE vec.embedding MATCH ?
                ORDER BY vec.distance
                LIMIT ?
                """,
                (query_vector, limit),
            ).fetchall()

        return [self._row_to_search_result(row) for row in rows]

    def _search_fallback(
        self,
        embedding: tuple[float, ...],
        limit: int,
    ) -> list[GameEmbeddingSearchResult]:
        with self._manager.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT game_id, dimension, embedding, metadata, created_at, updated_at
                FROM {self.TABLE_NAME}
                WHERE dimension = ?
                """,
                (self._dimension,),
            ).fetchall()

        records = [self._row_to_record(row) for row in rows]
        results: list[GameEmbeddingSearchResult] = []
        for record in records:
            distance = _calculate_distance(
                record.embedding,
                embedding,
                metric=self._distance_metric,
            )
            results.append(GameEmbeddingSearchResult(distance=distance, **record.to_dict()))

        results.sort(key=lambda item: item.distance)
        return results[:limit]

    def _sync_vec_index(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        embedding: tuple[float, ...],
    ) -> None:
        row = conn.execute(
            f"SELECT id FROM {self.TABLE_NAME} WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        if row is None:
            return
        row_id = row["id"]
        vector = json.dumps(embedding)
        conn.execute(
            f"DELETE FROM {self.VEC_TABLE_NAME} WHERE rowid = ?",
            (row_id,),
        )
        conn.execute(
            f"INSERT INTO {self.VEC_TABLE_NAME}(rowid, embedding) VALUES (?, ?)",
            (row_id, vector),
        )

    def _row_to_record(self, row: sqlite3.Row | None) -> GameEmbeddingRecord:
        if row is None:
            msg = "Row is required to build DTO"
            raise SQLiteVecError(msg)

        return GameEmbeddingRecord(
            game_id=row["game_id"],
            dimension=row["dimension"],
            embedding=_blob_to_embedding(row["embedding"], row["dimension"]),
            metadata=json.loads(row["metadata"]),
            created_at=_parse_timestamp(row["created_at"]),
            updated_at=_parse_timestamp(row["updated_at"]),
        )

    def _row_to_search_result(self, row: sqlite3.Row) -> GameEmbeddingSearchResult:
        record = self._row_to_record(row)
        return GameEmbeddingSearchResult(distance=row["distance"], **record.to_dict())


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
    buf.frombytes(blob)
    if len(buf) != dimension:
        raise SQLiteVecError("Stored embedding dimension mismatch")
    return tuple(float(value) for value in buf)


def _calculate_distance(
    left: Sequence[float],
    right: Sequence[float],
    *,
    metric: DistanceMetric,
) -> float:
    if len(left) != len(right):
        msg = "Cannot compute distance for mismatched dimensions"
        raise SQLiteVecError(msg)
    if metric == "l2":
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))

    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    denom = left_norm * right_norm
    if denom == 0:
        return 1.0
    cosine = dot / denom
    return 1.0 - cosine


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


__all__ = [
    "SQLiteVecConnectionManager",
    "SQLiteVecEmbeddingRepository",
    "GameEmbeddingPayload",
    "GameEmbeddingRecord",
    "GameEmbeddingSearchResult",
    "EmbeddingRepository",
    "seed_embeddings",
    "SQLiteVecError",
]
