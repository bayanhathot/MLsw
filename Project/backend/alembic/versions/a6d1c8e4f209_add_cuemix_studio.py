"""add CueMix Studio saved segments and revisioned drafts

Revision ID: a6d1c8e4f209
Revises: f5c9a3d7b1e2
Create Date: 2026-08-21 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6d1c8e4f209"
down_revision: str | Sequence[str] | None = "f5c9a3d7b1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_track_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("artist", sa.String(length=255), nullable=False),
        sa.Column("album", sa.String(length=255), nullable=True),
        sa.Column("genre", sa.String(length=100), nullable=True),
        sa.Column("vibe", sa.String(length=100), nullable=True),
        sa.Column("source_audio_url", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("track_duration_ms", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("created_from", sa.String(length=20), nullable=False),
        sa.Column("analysis_version", sa.String(length=20), nullable=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("bpm_confidence", sa.Float(), nullable=True),
        sa.Column("musical_key", sa.String(length=8), nullable=True),
        sa.Column("key_mode", sa.String(length=10), nullable=True),
        sa.Column("camelot", sa.String(length=4), nullable=True),
        sa.Column("key_confidence", sa.Float(), nullable=True),
        sa.Column("integrated_loudness_lufs", sa.Float(), nullable=True),
        sa.Column("phrase_boundaries_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('catalog', 'audius')",
            name="ck_saved_segment_source_type",
        ),
        sa.CheckConstraint(
            "created_from IN ('manual', 'ai', 'auto')",
            name="ck_saved_segment_created_from",
        ),
        sa.CheckConstraint(
            "start_ms >= 0 AND start_ms < end_ms AND end_ms <= track_duration_ms",
            name="ck_saved_segment_bounds",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_saved_segments_user_id", "saved_segments", ["user_id"])
    op.create_index(
        "ix_saved_segments_source_track_id", "saved_segments", ["source_track_id"]
    )

    with op.batch_alter_table("mixes") as batch:
        batch.add_column(
            sa.Column("is_studio", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("rendered_revision", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("published_revision", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "render_status",
                sa.String(length=20),
                nullable=False,
                server_default="not_rendered",
            )
        )
        batch.add_column(sa.Column("rendered_audio_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_audio_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_segments_json", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column(
                "visibility",
                sa.String(length=20),
                nullable=False,
                server_default="private",
            )
        )
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.create_check_constraint(
            "ck_mix_render_status",
            "render_status IN ('not_rendered', 'rendering', 'ready', 'stale', 'failed')",
        )
        batch.create_check_constraint(
            "ck_mix_visibility", "visibility IN ('private', 'public')"
        )

    op.execute(
        sa.text(
            "UPDATE mixes SET visibility = CASE WHEN status = 'published' "
            "THEN 'public' ELSE 'private' END"
        )
    )

    with op.batch_alter_table("mix_segments") as batch:
        batch.add_column(sa.Column("saved_segment_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_audio_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_start_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_end_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("bpm", sa.Float(), nullable=True))
        batch.add_column(sa.Column("musical_key", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("key_mode", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("camelot", sa.String(length=4), nullable=True))
        batch.add_column(
            sa.Column(
                "transition_type",
                sa.String(length=20),
                nullable=False,
                server_default="crossfade",
            )
        )
        batch.add_column(
            sa.Column(
                "transition_duration_ms",
                sa.Integer(),
                nullable=False,
                server_default="4000",
            )
        )
        batch.add_column(sa.Column("compatibility_score", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("compatibility_factors_json", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_mix_segments_saved_segment_id",
            "saved_segments",
            ["saved_segment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_mix_segments_saved_segment_id", ["saved_segment_id"], unique=False
        )

    op.create_table(
        "studio_behavior_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("saved_segment_id", sa.Integer(), nullable=True),
        sa.Column("mix_id", sa.Integer(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('segment_save', 'segment_replay', 'early_skip', 'mix_like')",
            name="ck_studio_behavior_event_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["saved_segment_id"], ["saved_segments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["mix_id"], ["mixes.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_studio_behavior_events_user_id", "studio_behavior_events", ["user_id"]
    )
    op.create_index(
        "ix_studio_behavior_events_event_type",
        "studio_behavior_events",
        ["event_type"],
    )
    op.create_index(
        "ix_studio_behavior_events_saved_segment_id",
        "studio_behavior_events",
        ["saved_segment_id"],
    )
    op.create_index(
        "ix_studio_behavior_events_mix_id", "studio_behavior_events", ["mix_id"]
    )


def downgrade() -> None:
    op.drop_table("studio_behavior_events")
    with op.batch_alter_table("mix_segments") as batch:
        batch.drop_index("ix_mix_segments_saved_segment_id")
        batch.drop_constraint("fk_mix_segments_saved_segment_id", type_="foreignkey")
        for column in (
            "compatibility_factors_json",
            "compatibility_score",
            "transition_duration_ms",
            "transition_type",
            "camelot",
            "key_mode",
            "musical_key",
            "bpm",
            "source_end_ms",
            "source_start_ms",
            "source_audio_url",
            "saved_segment_id",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("mixes") as batch:
        batch.drop_constraint("ck_mix_visibility", type_="check")
        batch.drop_constraint("ck_mix_render_status", type_="check")
        for column in (
            "updated_at",
            "visibility",
            "published_segments_json",
            "published_audio_url",
            "rendered_audio_url",
            "render_status",
            "published_revision",
            "rendered_revision",
            "revision",
            "is_studio",
        ):
            batch.drop_column(column)
    op.drop_table("saved_segments")
