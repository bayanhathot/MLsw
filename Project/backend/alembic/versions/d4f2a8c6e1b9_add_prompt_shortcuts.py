"""add prompt_shortcuts table for personalized prompt-shortcut chips

Revision ID: d4f2a8c6e1b9
Revises: c1d9a7e5f3b8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4f2a8c6e1b9"
down_revision: Union[str, Sequence[str], None] = "c1d9a7e5f3b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_shortcuts",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(length=160), nullable=False),
        sa.Column("prompt", sa.String(length=300), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "signature"),
    )


def downgrade() -> None:
    op.drop_table("prompt_shortcuts")
