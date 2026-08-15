"""consolidate AI-DJ pipeline: catalog_tracks + dj_sessions SessionState

Revision ID: e7b3d2a91f44
Revises: d9e4a71f3c10
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7b3d2a91f44"
down_revision: Union[str, Sequence[str], None] = "d9e4a71f3c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 4 legacy hardcoded TRACKS dict entries, now real catalog rows. All 4
# still point at the one bundled demo asset (catalog_retriever.py stages it
# into UPLOAD_DIR on first use) -- same as the old dict, which served every
# bucket from the same cuemix-demo.wav.
_SEED_TRACKS = [
    {
        "title": "Momentum Loop",
        "artist": "Cuemix AI DJ",
        "album": "Workout Demo Catalog",
        "mood_bucket": "energy",
        "vibe_label": "Gym energy",
    },
    {
        "title": "Midnight Whispers",
        "artist": "Cuemix AI DJ",
        "album": "Vocal Demo Catalog",
        "mood_bucket": "vocals",
        "vibe_label": "Emotional vocals",
    },
    {
        "title": "Focus Loop 01",
        "artist": "Cuemix AI DJ",
        "album": "Focus Demo Catalog",
        "mood_bucket": "focus",
        "vibe_label": "Deep work focus",
    },
    {
        "title": "Smooth Flow Demo",
        "artist": "Cuemix AI DJ",
        "album": "General Demo Catalog",
        "mood_bucket": "smooth",
        "vibe_label": "Smooth flow",
    },
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "catalog_tracks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("artist", sa.String(255), nullable=False),
        sa.Column("album", sa.String(255), nullable=True),
        sa.Column("lyrics", sa.Text(), nullable=True),
        sa.Column("genre", sa.String(100), nullable=True),
        sa.Column("mood_bucket", sa.String(20), nullable=True),
        sa.Column("vibe_label", sa.String(100), nullable=True),
        sa.Column("storage_name", sa.String(100), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analysis_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("musical_key", sa.String(8), nullable=True),
        sa.Column("segment_start_second", sa.Integer(), nullable=True),
        sa.Column("segment_end_second", sa.Integer(), nullable=True),
        sa.Column("segment_method", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "analysis_status IN ('pending', 'completed', 'failed', 'not_applicable')",
            name="ck_catalog_track_analysis_status",
        ),
        sa.CheckConstraint(
            "segment_method IS NULL OR segment_method IN ('chorus_detection', 'whole_clip')",
            name="ck_catalog_track_segment_method",
        ),
    )
    op.create_index("ix_catalog_tracks_owner_id", "catalog_tracks", ["owner_id"])
    op.create_index("ix_catalog_tracks_mood_bucket", "catalog_tracks", ["mood_bucket"])
    op.create_index("ix_catalog_tracks_storage_name", "catalog_tracks", ["storage_name"])
    op.create_index(
        "ix_catalog_tracks_artist_trgm",
        "catalog_tracks",
        ["artist"],
        postgresql_using="gin",
        postgresql_ops={"artist": "gin_trgm_ops"},
    )

    catalog_tracks_table = sa.table(
        "catalog_tracks",
        sa.column("title", sa.String),
        sa.column("artist", sa.String),
        sa.column("album", sa.String),
        sa.column("mood_bucket", sa.String),
        sa.column("vibe_label", sa.String),
        sa.column("storage_name", sa.String),
        sa.column("content_type", sa.String),
        sa.column("duration_seconds", sa.Integer),
        sa.column("analysis_status", sa.String),
        sa.column("segment_start_second", sa.Integer),
        sa.column("segment_end_second", sa.Integer),
        sa.column("segment_method", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(
        catalog_tracks_table,
        [
            {
                **seed,
                "storage_name": "cuemix-demo.wav",
                "content_type": "audio/wav",
                "duration_seconds": 60,
                "analysis_status": "completed",
                "segment_start_second": 0,
                "segment_end_second": 45,
                "segment_method": "whole_clip",
                "created_at": now,
            }
            for seed in _SEED_TRACKS
        ],
    )

    op.drop_constraint("ck_dj_session_track_key", "dj_sessions", type_="check")
    op.drop_column("dj_sessions", "track_key")
    op.add_column(
        "dj_sessions",
        sa.Column("retriever_name", sa.String(40), nullable=False, server_default="catalog"),
    )
    op.add_column(
        "dj_sessions", sa.Column("intent_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "dj_sessions", sa.Column("now_playing_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "dj_sessions", sa.Column("reasoning_json", sa.JSON(), nullable=False, server_default="{}")
    )


def downgrade() -> None:
    op.drop_column("dj_sessions", "reasoning_json")
    op.drop_column("dj_sessions", "now_playing_json")
    op.drop_column("dj_sessions", "intent_json")
    op.drop_column("dj_sessions", "retriever_name")
    op.add_column(
        "dj_sessions", sa.Column("track_key", sa.String(40), nullable=False, server_default="smooth")
    )
    op.create_check_constraint(
        "ck_dj_session_track_key",
        "dj_sessions",
        "track_key IN ('energy', 'vocals', 'focus', 'smooth')",
    )
    op.drop_table("catalog_tracks")
