"""add known_broken_tracks table for cross-session broken-audio memory

Revision ID: c1d9a7e5f3b8
Revises: fbb453a67fc8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1d9a7e5f3b8"
down_revision: Union[str, Sequence[str], None] = "fbb453a67fc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "known_broken_tracks",
        sa.Column("track_key", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_track_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("fallback_reason", sa.String(length=100), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("track_key"),
    )


def downgrade() -> None:
    op.drop_table("known_broken_tracks")
