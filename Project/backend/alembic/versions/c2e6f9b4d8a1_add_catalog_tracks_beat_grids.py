"""add catalog_tracks beat_grid_json, downbeat_grid_json, phrase_boundaries_json

Revision ID: c2e6f9b4d8a1
Revises: b7d4e1a9c3f6
Create Date: 2026-08-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2e6f9b4d8a1'
down_revision: Union[str, Sequence[str], None] = 'b7d4e1a9c3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No backfill, same reasoning as every other analysis-field addition in
    # this chain: existing rows were analyzed before beat-grid persistence
    # existed, so there's nothing to compute these from retroactively
    # without re-running analysis.
    op.add_column("catalog_tracks", sa.Column("beat_grid_json", sa.JSON(), nullable=True))
    op.add_column("catalog_tracks", sa.Column("downbeat_grid_json", sa.JSON(), nullable=True))
    op.add_column("catalog_tracks", sa.Column("phrase_boundaries_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("catalog_tracks", "phrase_boundaries_json")
    op.drop_column("catalog_tracks", "downbeat_grid_json")
    op.drop_column("catalog_tracks", "beat_grid_json")
