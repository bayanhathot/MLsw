"""add dj_sessions.played_track_keys_json for continuous session advancing

Revision ID: b3d5f8a1c9e2
Revises: a1c7f4e92b6d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3d5f8a1c9e2"
down_revision: Union[str, Sequence[str], None] = "a1c7f4e92b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dj_sessions", sa.Column("played_track_keys_json", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("dj_sessions", "played_track_keys_json")
