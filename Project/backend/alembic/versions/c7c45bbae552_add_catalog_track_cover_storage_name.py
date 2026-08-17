"""add catalog_tracks.cover_storage_name

Revision ID: c7c45bbae552
Revises: 73473b84e848
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7c45bbae552"
down_revision: Union[str, Sequence[str], None] = "73473b84e848"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_tracks", sa.Column("cover_storage_name", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("catalog_tracks", "cover_storage_name")
