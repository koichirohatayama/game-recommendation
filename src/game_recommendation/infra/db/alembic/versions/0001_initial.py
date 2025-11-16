"""初期スキーマ"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "igdb_games",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("igdb_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("slug", sa.String(), unique=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags_cache", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("release_date", sa.String()),
        sa.Column("cover_url", sa.String()),
        sa.Column("summary", sa.Text()),
        sa.Column("checksum", sa.String()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_igdb_games_release", "igdb_games", ["release_date"])

    op.create_table(
        "game_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "game_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("game_id", sa.String(), nullable=False, unique=True),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_game_embeddings_game_id", "game_embeddings", ["game_id"])
    op.create_index("idx_game_embeddings_dimension", "game_embeddings", ["dimension"])

    op.create_table(
        "game_tag_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("igdb_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("game_tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("game_id", "tag_id"),
    )
    op.create_index("idx_game_tag_links_game_id", "game_tag_links", ["game_id"])

    op.create_table(
        "user_favorite_games",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("igdb_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "added_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("game_id"),
    )


def downgrade() -> None:
    op.drop_table("user_favorite_games")
    op.drop_index("idx_game_tag_links_game_id", table_name="game_tag_links")
    op.drop_table("game_tag_links")
    op.drop_table("game_tags")
    op.drop_index("idx_game_embeddings_dimension", table_name="game_embeddings")
    op.drop_index("idx_game_embeddings_game_id", table_name="game_embeddings")
    op.drop_table("game_embeddings")
    op.drop_index("idx_igdb_games_release", table_name="igdb_games")
    op.drop_table("igdb_games")
