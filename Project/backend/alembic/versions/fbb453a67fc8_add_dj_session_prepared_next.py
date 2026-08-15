"""add dj_sessions.prepared_next_json for prefetched next-track state

Revision ID: fbb453a67fc8
Revises: 48912bd792ef
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "fbb453a67fc8"
down_revision: Union[str, Sequence[str], None] = "48912bd792ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dj_sessions", sa.Column("prepared_next_json", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("dj_sessions", "prepared_next_json")
