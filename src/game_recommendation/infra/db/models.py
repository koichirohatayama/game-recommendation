"""DB スキーマの SQLAlchemy モデル。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IgdbGame(Base):
    __tablename__ = "igdb_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    igdb_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    slug: Mapped[str | None] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags_cache: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    release_date: Mapped[str | None] = mapped_column(String)
    cover_url: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (Index("idx_igdb_games_release", "release_date"),)


class GameTag(Base):
    __tablename__ = "game_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class GameTagLink(Base):
    __tablename__ = "game_tag_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("igdb_games.id", ondelete="CASCADE"),
    )
    tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("game_tags.id", ondelete="CASCADE"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("game_id", "tag_id"),
        Index("idx_game_tag_links_game_id", "game_id"),
    )


class UserFavoriteGame(Base):
    __tablename__ = "user_favorite_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("igdb_games.id", ondelete="CASCADE"),
    )
    notes: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (UniqueConstraint("game_id"),)


class GameEmbedding(Base):
    __tablename__ = "game_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_game_embeddings_game_id", "game_id"),
        Index("idx_game_embeddings_dimension", "dimension"),
    )


__all__ = [
    "Base",
    "GameEmbedding",
    "GameTag",
    "GameTagLink",
    "IgdbGame",
    "UserFavoriteGame",
]
