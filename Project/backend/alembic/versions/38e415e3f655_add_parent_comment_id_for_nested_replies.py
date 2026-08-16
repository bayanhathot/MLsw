"""add forum_comments.parent_comment_id for nested replies

Revision ID: 38e415e3f655
Revises: 7a2e91c4d8f0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "38e415e3f655"
down_revision: Union[str, Sequence[str], None] = "7a2e91c4d8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("forum_comments", sa.Column("parent_comment_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_forum_comments_parent_comment_id", "forum_comments", ["parent_comment_id"]
    )
    op.create_foreign_key(
        "fk_forum_comments_parent_comment_id",
        "forum_comments",
        "forum_comments",
        ["parent_comment_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_forum_comments_parent_comment_id", "forum_comments", type_="foreignkey")
    op.drop_index("ix_forum_comments_parent_comment_id", table_name="forum_comments")
    op.drop_column("forum_comments", "parent_comment_id")
