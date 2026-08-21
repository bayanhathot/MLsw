"""add literal auto-mix modes

Revision ID: e4b8c2d6f0a1
Revises: d3f8a2c6e9b1
Create Date: 2026-08-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4b8c2d6f0a1"
down_revision: str | Sequence[str] | None = "d3f8a2c6e9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_MODES = "'workout', 'relaxation', 'emotional_tarab', 'party'"


def upgrade() -> None:
    op.add_column("dj_sessions", sa.Column("mode", sa.String(length=32), nullable=True))
    op.add_column("mixes", sa.Column("mode", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        "ck_dj_session_mode",
        "dj_sessions",
        f"mode IS NULL OR mode IN ({_VALID_MODES})",
    )
    op.create_check_constraint(
        "ck_mix_mode",
        "mixes",
        f"mode IS NULL OR mode IN ({_VALID_MODES})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mix_mode", "mixes", type_="check")
    op.drop_constraint("ck_dj_session_mode", "dj_sessions", type_="check")
    op.drop_column("mixes", "mode")
    op.drop_column("dj_sessions", "mode")
