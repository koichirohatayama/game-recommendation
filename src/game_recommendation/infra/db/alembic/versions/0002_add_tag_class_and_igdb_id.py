"""タグ分類とIGDB ID の追加

game_tags テーブルに tag_class と igdb_id カラムを追加し、
IGDB API の genres/keywords/themes/franchises/collections を区別できるようにする
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_tag_class_and_igdb_id"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 一時的に外部キー制約を無効化（SQLite）
    op.execute("PRAGMA foreign_keys=OFF")

    # 新しいテーブルを作成
    op.create_table(
        "game_tags_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("tag_class", sa.String(), nullable=False),
        sa.Column("igdb_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("slug", "tag_class", name="uq_game_tags_slug_class"),
        sa.UniqueConstraint("igdb_id", "tag_class", name="uq_game_tags_igdb_id_class"),
    )

    # インデックスを作成
    op.create_index("idx_game_tags_igdb_id", "game_tags_new", ["igdb_id"])
    op.create_index("idx_game_tags_tag_class", "game_tags_new", ["tag_class"])

    # 既存データを移行（もしあれば）
    op.execute(
        """
        INSERT INTO game_tags_new (id, slug, label, tag_class, igdb_id, created_at)
        SELECT id, slug, label, 'unknown', NULL, created_at
        FROM game_tags
        """
    )

    # 古いテーブルを削除
    op.drop_table("game_tags")

    # 新しいテーブルをリネーム
    op.rename_table("game_tags_new", "game_tags")

    # 外部キー制約を再度有効化
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    # 新しいテーブルを作成（元の構造）
    op.create_table(
        "game_tags_old",
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

    # データを戻す
    op.execute(
        """
        INSERT INTO game_tags_old (id, slug, label, created_at)
        SELECT id, slug, label, created_at
        FROM game_tags
        """
    )

    # 古いテーブルを削除
    op.drop_index("idx_game_tags_tag_class", table_name="game_tags")
    op.drop_index("idx_game_tags_igdb_id", table_name="game_tags")
    op.drop_table("game_tags")

    # 新しいテーブルをリネーム
    op.rename_table("game_tags_old", "game_tags")
