"""add sessions, social mixes, profiles, forum and messaging

Revision ID: b4c51d9e3a20
Revises: 92efbb2c2a49
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4c51d9e3a20"
down_revision: Union[str, Sequence[str], None] = "92efbb2c2a49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dj_sessions",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("vibe_label", sa.String(100), nullable=False),
        sa.Column("track_key", sa.String(40), nullable=False),
        sa.Column("selected_feedback", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('playing', 'stopped')", name="ck_dj_session_status"),
        sa.CheckConstraint(
            "track_key IN ('energy', 'vocals', 'focus', 'smooth')",
            name="ck_dj_session_track_key",
        ),
    )
    op.create_index("ix_dj_sessions_user_id", "dj_sessions", ["user_id"])
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("feedback", sa.String(40), primary_key=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "session_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(48), sa.ForeignKey("dj_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feedback", sa.String(100), nullable=False),
        sa.Column("normalized_feedback", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_session_feedback_session_id", "session_feedback", ["session_id"])
    op.create_index("ix_session_feedback_user_id", "session_feedback", ["user_id"])

    op.create_table(
        "mixes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(48), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("prompt", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_mix_status"),
    )
    op.create_index("ix_mixes_session_id", "mixes", ["session_id"], unique=True)
    op.create_index("ix_mixes_owner_id", "mixes", ["owner_id"])
    op.create_index("ix_mixes_status", "mixes", ["status"])
    op.create_table(
        "mix_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mix_id", sa.Integer(), sa.ForeignKey("mixes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("artist", sa.String(255), nullable=False),
        sa.Column("audio_url", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("start_second", sa.Integer(), nullable=False),
        sa.Column("end_second", sa.Integer(), nullable=False),
        sa.Column("transition_to_next", sa.String(50), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_track_id", sa.String(255), nullable=False),
        sa.UniqueConstraint("mix_id", "position", name="uq_mix_segment_position"),
    )
    op.create_index("ix_mix_segments_mix_id", "mix_segments", ["mix_id"])
    for table in ("mix_likes", "saved_mixes"):
        constraint = "uq_user_mix_like" if table == "mix_likes" else "uq_user_saved_mix"
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mix_id", sa.Integer(), sa.ForeignKey("mixes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "mix_id", name=constraint),
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
        op.create_index(f"ix_{table}_mix_id", table, ["mix_id"])

    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column("avatar_url", sa.String(1000), nullable=True),
        sa.Column("bio", sa.String(280), nullable=True),
        sa.Column("favorite_genres", sa.JSON(), nullable=True),
        sa.Column("theme_preference", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("theme_preference IN ('dark', 'light', 'system')", name="ck_profile_theme"),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=True)

    op.create_table(
        "forum_posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_forum_posts_author_id", "forum_posts", ["author_id"])
    op.create_index("ix_forum_posts_created_at", "forum_posts", ["created_at"])
    op.create_table(
        "forum_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_forum_comments_post_id", "forum_comments", ["post_id"])
    op.create_index("ix_forum_comments_author_id", "forum_comments", ["author_id"])
    op.create_index("ix_forum_comments_created_at", "forum_comments", ["created_at"])
    op.create_table(
        "forum_post_votes",
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_forum_post_vote_value"),
    )
    op.create_table(
        "forum_comment_votes",
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("forum_comments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_forum_comment_vote_value"),
    )

    op.create_table(
        "direct_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("sender_id <> recipient_id", name="ck_direct_message_not_self"),
    )
    op.create_index("ix_direct_messages_sender_id", "direct_messages", ["sender_id"])
    op.create_index("ix_direct_messages_recipient_id", "direct_messages", ["recipient_id"])
    op.create_index("ix_direct_messages_created_at", "direct_messages", ["created_at"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("storage_name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("forum_comments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("direct_messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('image', 'video', 'audio')", name="ck_attachment_kind"),
        sa.CheckConstraint("size_bytes > 0", name="ck_attachment_nonempty"),
        sa.CheckConstraint(
            "(CASE WHEN post_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN comment_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN message_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="ck_attachment_single_parent",
        ),
        sa.UniqueConstraint("storage_name", name="uq_attachments_storage_name"),
    )
    for column in ("owner_id", "post_id", "comment_id", "message_id"):
        op.create_index(f"ix_attachments_{column}", "attachments", [column])


def downgrade() -> None:
    for table in (
        "attachments",
        "notifications",
        "direct_messages",
        "forum_comment_votes",
        "forum_post_votes",
        "forum_comments",
        "forum_posts",
        "profiles",
        "saved_mixes",
        "mix_likes",
        "mix_segments",
        "mixes",
        "session_feedback",
        "user_preferences",
        "dj_sessions",
    ):
        op.drop_table(table)
