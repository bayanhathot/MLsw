"""add catalog_tracks bpm_confidence and key_confidence

Revision ID: 5261424ebc26
Revises: f59dc31eb177
Create Date: 2026-08-18 14:22:17.230919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5261424ebc26'
down_revision: Union[str, Sequence[str], None] = 'f59dc31eb177'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No backfill, same reasoning as analysis_version/analyzed_at: existing
    # rows were analyzed before this signal existed, so there's nothing
    # accurate to compute it from retroactively without re-running analysis.
    op.add_column("catalog_tracks", sa.Column("bpm_confidence", sa.Float(), nullable=True))
    op.add_column("catalog_tracks", sa.Column("key_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("catalog_tracks", "key_confidence")
    op.drop_column("catalog_tracks", "bpm_confidence")
