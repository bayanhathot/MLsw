"""add dj_sessions.played_artists_json for session-aware artist diversity ranking

Revision ID: f7cf2e9fcb1d
Revises: b3d5f8a1c9e2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f7cf2e9fcb1d"
down_revision: Union[str, Sequence[str], None] = "b3d5f8a1c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dj_sessions", sa.Column("played_artists_json", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("dj_sessions", "played_artists_json")
