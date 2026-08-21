"""add source-track duration to persisted mix segments

Revision ID: f5c9a3d7b1e2
Revises: e4b8c2d6f0a1
Create Date: 2026-08-21 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5c9a3d7b1e2"
down_revision: str | Sequence[str] | None = "e4b8c2d6f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mix_segments",
        sa.Column("track_duration_seconds", sa.Integer(), nullable=True),
    )
    # Backfill persisted segments from the authoritative provider/catalog
    # identity tables where possible. Older rows with no retained provider
    # metadata remain null and the runtime safely falls back to their rendered
    # clip bounds instead of inventing a source duration.
    op.execute(
        sa.text(
            "UPDATE mix_segments SET track_duration_seconds = ("
            "SELECT catalog_tracks.duration_seconds FROM catalog_tracks "
            "WHERE CAST(catalog_tracks.id AS VARCHAR) = mix_segments.source_track_id"
            ") WHERE mix_segments.source = 'catalog' AND EXISTS ("
            "SELECT 1 FROM catalog_tracks WHERE "
            "CAST(catalog_tracks.id AS VARCHAR) = mix_segments.source_track_id)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE mix_segments SET track_duration_seconds = ("
            "SELECT external_tracks.duration_sec FROM external_tracks "
            "WHERE external_tracks.source = mix_segments.source "
            "AND external_tracks.external_id = mix_segments.source_track_id"
            ") WHERE EXISTS (SELECT 1 FROM external_tracks WHERE "
            "external_tracks.source = mix_segments.source "
            "AND external_tracks.external_id = mix_segments.source_track_id)"
        )
    )
    # Repair historical ListeningEvent duration snapshots from the same
    # authoritative identities. This makes the new time-saved metric useful
    # immediately after deployment rather than only for future plays.
    op.execute(
        sa.text(
            "UPDATE listening_events SET track_duration_seconds = ("
            "SELECT catalog_tracks.duration_seconds FROM catalog_tracks "
            "WHERE CAST(catalog_tracks.id AS VARCHAR) = listening_events.source_track_id"
            ") WHERE listening_events.source = 'catalog' AND EXISTS ("
            "SELECT 1 FROM catalog_tracks WHERE "
            "CAST(catalog_tracks.id AS VARCHAR) = listening_events.source_track_id)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE listening_events SET track_duration_seconds = ("
            "SELECT external_tracks.duration_sec FROM external_tracks "
            "WHERE external_tracks.source = listening_events.source "
            "AND external_tracks.external_id = listening_events.source_track_id"
            ") WHERE EXISTS (SELECT 1 FROM external_tracks WHERE "
            "external_tracks.source = listening_events.source "
            "AND external_tracks.external_id = listening_events.source_track_id)"
        )
    )


def downgrade() -> None:
    op.drop_column("mix_segments", "track_duration_seconds")
