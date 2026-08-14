"""add dj_sessions.original_intent_json to preserve the session's initial intent

Revision ID: 48912bd792ef
Revises: f7cf2e9fcb1d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "48912bd792ef"
down_revision: Union[str, Sequence[str], None] = "f7cf2e9fcb1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dj_sessions", sa.Column("original_intent_json", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("dj_sessions", "original_intent_json")
