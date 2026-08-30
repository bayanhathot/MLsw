"""add dj_sessions.mix_scope

Revision ID: 7a1fd06682ce
Revises: 646dfa7ecf85
Create Date: 2026-08-30 00:00:00.000000

Additive only: every existing session row gets the new column's
server_default ('segments'), which is byte-identical to how every session
already behaved before this column existed (LibrosaSegmentSelector, the
only SegmentSelector in production until now).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a1fd06682ce"
down_revision: Union[str, Sequence[str], None] = "646dfa7ecf85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dj_sessions",
        sa.Column(
            "mix_scope",
            sa.String(length=20),
            nullable=False,
            server_default="segments",
        ),
    )
    op.create_check_constraint(
        "ck_dj_session_mix_scope",
        "dj_sessions",
        "mix_scope IN ('segments', 'full_songs')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_dj_session_mix_scope", "dj_sessions", type_="check")
    op.drop_column("dj_sessions", "mix_scope")
