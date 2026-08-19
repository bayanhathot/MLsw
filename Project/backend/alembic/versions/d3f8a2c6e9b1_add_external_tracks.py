"""add external_tracks

Revision ID: d3f8a2c6e9b1
Revises: c2e6f9b4d8a1
Create Date: 2026-08-19 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f8a2c6e9b1'
down_revision: Union[str, Sequence[str], None] = 'c2e6f9b4d8a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_tracks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("artist", sa.String(length=255), nullable=False),
        sa.Column("album", sa.String(length=255), nullable=True),
        sa.Column("genre", sa.String(length=100), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_metadata_json", sa.JSON(), nullable=True),
        sa.Column("audio_sha256", sa.String(length=64), nullable=True),
        sa.Column("analysis_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("analysis_version", sa.String(length=20), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        sa.Column("analysis_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analysis_last_failed_at", sa.DateTime(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("bpm_confidence", sa.Float(), nullable=True),
        sa.Column("musical_key", sa.String(length=8), nullable=True),
        sa.Column("key_mode", sa.String(length=10), nullable=True),
        sa.Column("camelot", sa.String(length=4), nullable=True),
        sa.Column("key_confidence", sa.Float(), nullable=True),
        sa.Column("integrated_loudness_lufs", sa.Float(), nullable=True),
        sa.Column("beat_grid_json", sa.JSON(), nullable=True),
        sa.Column("downbeat_grid_json", sa.JSON(), nullable=True),
        sa.Column("phrase_boundaries_json", sa.JSON(), nullable=True),
        sa.Column("segment_start_second", sa.Integer(), nullable=True),
        sa.Column("segment_end_second", sa.Integer(), nullable=True),
        sa.Column("segment_method", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "analysis_status IN ('pending', 'completed', 'failed', 'not_applicable')",
            name="ck_external_track_analysis_status",
        ),
        sa.CheckConstraint(
            "segment_method IS NULL OR segment_method IN ('chorus_detection', 'whole_clip')",
            name="ck_external_track_segment_method",
        ),
        sa.UniqueConstraint("source", "external_id", name="uq_external_tracks_source_external_id"),
    )
    op.create_index(
        "ix_external_tracks_source_external_id", "external_tracks", ["source", "external_id"]
    )
    op.create_index(
        "ix_external_tracks_analysis_version", "external_tracks", ["analysis_version"]
    )


def downgrade() -> None:
    op.drop_index("ix_external_tracks_analysis_version", table_name="external_tracks")
    op.drop_index("ix_external_tracks_source_external_id", table_name="external_tracks")
    op.drop_table("external_tracks")
