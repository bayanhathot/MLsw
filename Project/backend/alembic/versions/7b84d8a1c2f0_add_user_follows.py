"""add user follows

Revision ID: 7b84d8a1c2f0
Revises: f3dc072dcac2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b84d8a1c2f0"
down_revision: Union[str, Sequence[str], None] = "f3dc072dcac2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_follows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("follower_id", sa.Integer(), nullable=False),
        sa.Column("following_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "follower_id <> following_id",
            name="ck_user_cannot_follow_self",
        ),
        sa.ForeignKeyConstraint(
            ["follower_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["following_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "follower_id",
            "following_id",
            name="uq_user_follow_relationship",
        ),
    )
    op.create_index(
        op.f("ix_user_follows_follower_id"),
        "user_follows",
        ["follower_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_follows_following_id"),
        "user_follows",
        ["following_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_follows_following_id"),
        table_name="user_follows",
    )
    op.drop_index(
        op.f("ix_user_follows_follower_id"),
        table_name="user_follows",
    )
    op.drop_table("user_follows")
