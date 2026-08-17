"""default catalog_tracks.visibility to public

Revision ID: 5920c091f88a
Revises: c7c45bbae552
Create Date: 2026-08-17 19:48:52.763851

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5920c091f88a'
down_revision: Union[str, Sequence[str], None] = 'c7c45bbae552'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only the column's default for *new* rows changes -- deliberately no
    # backfill of existing rows here. A user who already uploaded a track as
    # "private" chose that, and flipping it to public out from under them on
    # a routine migration would be a real privacy regression, not a neutral
    # schema change.
    op.alter_column(
        "catalog_tracks", "visibility", server_default="public", existing_type=sa.String(length=20)
    )


def downgrade() -> None:
    op.alter_column(
        "catalog_tracks", "visibility", server_default="private", existing_type=sa.String(length=20)
    )
