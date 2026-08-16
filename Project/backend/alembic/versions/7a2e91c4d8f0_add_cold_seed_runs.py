"""add cold_seed_runs table for the cold-seed idempotency marker

Revision ID: 7a2e91c4d8f0
Revises: d4f2a8c6e1b9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7a2e91c4d8f0"
down_revision: Union[str, Sequence[str], None] = "d4f2a8c6e1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cold_seed_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("version", name="uq_cold_seed_runs_version"),
    )
    op.create_index("ix_cold_seed_runs_version", "cold_seed_runs", ["version"])


def downgrade() -> None:
    op.drop_table("cold_seed_runs")
