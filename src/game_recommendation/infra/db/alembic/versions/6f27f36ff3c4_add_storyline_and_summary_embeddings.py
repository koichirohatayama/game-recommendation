"""Add storyline and summary embeddings to game_embeddings."""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "6f27f36ff3c4"
down_revision = "a2f2f2dff908"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("game_embeddings") as batch_op:
        batch_op.add_column(sa.Column("storyline_embedding", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("summary_embedding", sa.LargeBinary(), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE game_embeddings
            SET storyline_embedding = description_embedding,
                summary_embedding = description_embedding
            """
        )
    )

    with op.batch_alter_table("game_embeddings") as batch_op:
        batch_op.alter_column("storyline_embedding", existing_type=sa.LargeBinary(), nullable=False)
        batch_op.alter_column("summary_embedding", existing_type=sa.LargeBinary(), nullable=False)
        batch_op.drop_column("description_embedding")


def downgrade() -> None:
    with op.batch_alter_table("game_embeddings") as batch_op:
        batch_op.add_column(sa.Column("description_embedding", sa.LargeBinary(), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE game_embeddings
            SET description_embedding = summary_embedding
            """
        )
    )

    with op.batch_alter_table("game_embeddings") as batch_op:
        batch_op.alter_column(
            "description_embedding", existing_type=sa.LargeBinary(), nullable=False
        )
        batch_op.drop_column("storyline_embedding")
        batch_op.drop_column("summary_embedding")
