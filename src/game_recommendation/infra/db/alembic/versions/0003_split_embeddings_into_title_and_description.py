"""Split embedding column into title/description embeddings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_split_embeddings_into_title_and_description"
down_revision = "0002_add_tag_class_and_igdb_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 一時的に外部キー制約を無効化（SQLite）
    op.execute("DROP TABLE IF EXISTS game_embeddings_vec")
    op.execute("DROP TABLE IF EXISTS game_embeddings_new")
    op.execute("DROP INDEX IF EXISTS idx_game_embeddings_game_id")
    op.execute("DROP INDEX IF EXISTS idx_game_embeddings_dimension")
    op.execute("PRAGMA foreign_keys=OFF")

    op.create_table(
        "game_embeddings_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("game_id", sa.String(), nullable=False, unique=True),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("title_embedding", sa.LargeBinary(), nullable=False),
        sa.Column("description_embedding", sa.LargeBinary(), nullable=False),
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
    op.create_index("idx_game_embeddings_game_id", "game_embeddings_new", ["game_id"])
    op.create_index("idx_game_embeddings_dimension", "game_embeddings_new", ["dimension"])

    op.execute(
        """
        INSERT INTO game_embeddings_new (
            id, game_id, dimension, title_embedding, description_embedding,
            metadata, created_at, updated_at
        )
        SELECT
            id, game_id, dimension, embedding, embedding,
            metadata, created_at, updated_at
        FROM game_embeddings
        """
    )

    op.drop_table("game_embeddings")
    op.rename_table("game_embeddings_new", "game_embeddings")

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS game_embeddings_vec")
    op.execute("DROP TABLE IF EXISTS game_embeddings_old")
    op.execute("DROP INDEX IF EXISTS idx_game_embeddings_game_id")
    op.execute("DROP INDEX IF EXISTS idx_game_embeddings_dimension")
    op.execute("PRAGMA foreign_keys=OFF")

    op.create_table(
        "game_embeddings_old",
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
    op.create_index("idx_game_embeddings_game_id", "game_embeddings_old", ["game_id"])
    op.create_index("idx_game_embeddings_dimension", "game_embeddings_old", ["dimension"])

    op.execute(
        """
        INSERT INTO game_embeddings_old (
            id, game_id, dimension, embedding, metadata, created_at, updated_at
        )
        SELECT
            id, game_id, dimension, description_embedding, metadata, created_at, updated_at
        FROM game_embeddings
        """
    )

    op.drop_table("game_embeddings")
    op.rename_table("game_embeddings_old", "game_embeddings")

    op.execute("PRAGMA foreign_keys=ON")
