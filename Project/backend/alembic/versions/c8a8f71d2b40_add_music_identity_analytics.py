"""add Music Identity analytics and raw listening events

Revision ID: c8a8f71d2b40
Revises: b4c51d9e3a20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8a8f71d2b40"
down_revision: Union[str, Sequence[str], None] = "b4c51d9e3a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mix_segments", sa.Column("genre", sa.String(length=100), nullable=True))
    op.add_column("mix_segments", sa.Column("vibe", sa.String(length=100), nullable=True))

    op.create_table(
        "user_music_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dna_status", sa.String(30), nullable=False, server_default="not_generated"),
        sa.Column("dna_label", sa.String(100), nullable=True),
        sa.Column("dna_summary", sa.Text(), nullable=True),
        sa.Column("dna_features", sa.JSON(), nullable=True),
        sa.Column("dna_version", sa.String(50), nullable=True),
        sa.Column("dna_updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_music_profiles_user_id", "user_music_profiles", ["user_id"], unique=True)

    op.create_table(
        "listening_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_event_id", sa.String(80), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(48), sa.ForeignKey("dj_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mix_id", sa.Integer(), sa.ForeignKey("mixes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("mix_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_track_id", sa.String(255), nullable=False),
        sa.Column("track_title", sa.String(255), nullable=False),
        sa.Column("artist_name", sa.String(255), nullable=False),
        sa.Column("genre", sa.String(100), nullable=True),
        sa.Column("vibe", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("seconds_listened", sa.Integer(), nullable=False),
        sa.Column("track_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("segment_start_second", sa.Integer(), nullable=True),
        sa.Column("segment_end_second", sa.Integer(), nullable=True),
        sa.Column("completion_ratio", sa.Float(), nullable=True),
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_event_id", name="uq_listening_event_client_id"),
        sa.CheckConstraint("seconds_listened >= 0", name="ck_listening_seconds_nonnegative"),
        sa.CheckConstraint(
            "completion_ratio IS NULL OR (completion_ratio >= 0 AND completion_ratio <= 1)",
            name="ck_listening_completion_ratio",
        ),
    )
    for column in (
        "client_event_id",
        "user_id",
        "session_id",
        "mix_id",
        "segment_id",
        "artist_name",
        "genre",
        "vibe",
        "started_at",
    ):
        op.create_index(f"ix_listening_events_{column}", "listening_events", [column])

    # Existing users should also receive a private Music Identity settings row.
    op.execute(
        sa.text(
            "INSERT INTO user_music_profiles (user_id, is_public, dna_status, created_at, updated_at) "
            "SELECT id, false, 'not_generated', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM users "
            "WHERE id NOT IN (SELECT user_id FROM user_music_profiles)"
        )
    )


def downgrade() -> None:
    op.drop_table("listening_events")
    op.drop_table("user_music_profiles")
    op.drop_column("mix_segments", "vibe")
    op.drop_column("mix_segments", "genre")
