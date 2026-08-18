"""fix bundled demo seed catalog rows' analysis_status to not_applicable

Revision ID: 948aec532585
Revises: 5261424ebc26
Create Date: 2026-08-18 20:45:45.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "948aec532585"
down_revision: Union[str, Sequence[str], None] = "5261424ebc26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 4 bundled demo rows (originally inserted by e7b3d2a91f44's data
# insert / mirrored in catalog_retriever._SEED_TRACKS) were inserted with
# analysis_status="completed" even though they never went through real
# librosa analysis -- bpm/musical_key were never set for them.
# "completed" is supposed to mean "librosa analyzed this and here's what
# it found" (audio_analysis.py always sets bpm/musical_key in the same
# commit as "completed"); these 4 rows were indistinguishable from a
# genuinely analyzed row to anything reading analysis_status alone. Fixes
# any database that already ran e7b3d2a91f44 before that migration's
# insert was corrected to use "not_applicable" directly -- a fresh
# `alembic upgrade head` on an empty database gets the corrected value
# straight from that migration, so this UPDATE simply matches nothing
# (and is a no-op) there.
_SEED_TITLES = ("Momentum Loop", "Midnight Whispers", "Focus Loop 01", "Smooth Flow Demo")


def _catalog_tracks_table() -> sa.Table:
    return sa.table(
        "catalog_tracks",
        sa.column("title", sa.String),
        sa.column("artist", sa.String),
        sa.column("storage_name", sa.String),
        sa.column("analysis_status", sa.String),
        sa.column("bpm", sa.Float),
    )


def upgrade() -> None:
    catalog_tracks = _catalog_tracks_table()
    op.execute(
        catalog_tracks.update()
        .where(
            catalog_tracks.c.title.in_(_SEED_TITLES),
            catalog_tracks.c.artist == "Cuemix AI DJ",
            catalog_tracks.c.storage_name == "cuemix-demo.wav",
            catalog_tracks.c.analysis_status == "completed",
            catalog_tracks.c.bpm.is_(None),
        )
        .values(analysis_status="not_applicable")
    )


def downgrade() -> None:
    catalog_tracks = _catalog_tracks_table()
    op.execute(
        catalog_tracks.update()
        .where(
            catalog_tracks.c.title.in_(_SEED_TITLES),
            catalog_tracks.c.artist == "Cuemix AI DJ",
            catalog_tracks.c.storage_name == "cuemix-demo.wav",
            catalog_tracks.c.analysis_status == "not_applicable",
            catalog_tracks.c.bpm.is_(None),
        )
        .values(analysis_status="completed")
    )
