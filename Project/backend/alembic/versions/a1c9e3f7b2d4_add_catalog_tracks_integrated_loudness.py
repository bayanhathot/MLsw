"""add catalog_tracks integrated_loudness_lufs

Revision ID: a1c9e3f7b2d4
Revises: 948aec532585
Create Date: 2026-08-18 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e3f7b2d4'
down_revision: Union[str, Sequence[str], None] = '948aec532585'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No backfill, same reasoning as bpm_confidence/key_confidence: existing
    # rows were analyzed before this signal existed, so there's nothing
    # accurate to compute it from retroactively without re-running analysis.
    op.add_column(
        "catalog_tracks", sa.Column("integrated_loudness_lufs", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("catalog_tracks", "integrated_loudness_lufs")
