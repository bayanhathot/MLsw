"""add dj_sessions.pipeline_trace_json for the internal pipeline debug panel

Revision ID: a1c7f4e92b6d
Revises: e7b3d2a91f44
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1c7f4e92b6d"
down_revision: Union[str, Sequence[str], None] = "e7b3d2a91f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dj_sessions", sa.Column("pipeline_trace_json", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("dj_sessions", "pipeline_trace_json")
