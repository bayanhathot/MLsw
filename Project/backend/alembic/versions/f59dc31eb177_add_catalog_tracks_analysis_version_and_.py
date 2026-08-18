"""add catalog_tracks analysis_version and analyzed_at

Revision ID: f59dc31eb177
Revises: 5920c091f88a
Create Date: 2026-08-18 13:27:21.569084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f59dc31eb177'
down_revision: Union[str, Sequence[str], None] = '5920c091f88a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No backfill for existing rows, even ones already analysis_status =
    # 'completed': we don't actually know which pipeline build or when they
    # were analyzed pre-this-column, and guessing would defeat the whole
    # point (a NULL here is an honest "unknown vintage" signal that future
    # reprocessing tooling should pick up, not data loss).
    op.add_column("catalog_tracks", sa.Column("analysis_version", sa.String(length=20), nullable=True))
    op.add_column("catalog_tracks", sa.Column("analyzed_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_catalog_tracks_analysis_version", "catalog_tracks", ["analysis_version"]
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_tracks_analysis_version", table_name="catalog_tracks")
    op.drop_column("catalog_tracks", "analyzed_at")
    op.drop_column("catalog_tracks", "analysis_version")
