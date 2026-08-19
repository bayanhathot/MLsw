"""add catalog_tracks key_mode and camelot

Revision ID: b7d4e1a9c3f6
Revises: a1c9e3f7b2d4
Create Date: 2026-08-19 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4e1a9c3f6'
down_revision: Union[str, Sequence[str], None] = 'a1c9e3f7b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No backfill, same reasoning as every other analysis-field addition in
    # this chain: existing rows were analyzed before real key-finding
    # existed (analysis_version="v1"), so there's nothing accurate to
    # compute key_mode/camelot from retroactively without re-running
    # analysis under the new v2 approach.
    op.add_column("catalog_tracks", sa.Column("key_mode", sa.String(length=10), nullable=True))
    op.add_column("catalog_tracks", sa.Column("camelot", sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column("catalog_tracks", "camelot")
    op.drop_column("catalog_tracks", "key_mode")
