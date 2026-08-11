"""add music social graph and community metadata

Revision ID: d9e4a71f3c10
Revises: c8a8f71d2b40
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e4a71f3c10"
down_revision: Union[str, Sequence[str], None] = "c8a8f71d2b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("forum_posts", sa.Column("kind", sa.String(length=20), nullable=False, server_default="discussion"))
    op.add_column("forum_posts", sa.Column("visibility", sa.String(length=20), nullable=False, server_default="public"))
    op.add_column("forum_posts", sa.Column("mix_id", sa.Integer(), nullable=True))
    op.create_index("ix_forum_posts_kind", "forum_posts", ["kind"])
    op.create_index("ix_forum_posts_visibility", "forum_posts", ["visibility"])
    op.create_index("ix_forum_posts_mix_id", "forum_posts", ["mix_id"])
    op.create_foreign_key("fk_forum_posts_mix_id", "forum_posts", "mixes", ["mix_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_forum_post_kind", "forum_posts", "kind IN ('discussion', 'status', 'mix_share')")
    op.create_check_constraint("ck_forum_post_visibility", "forum_posts", "visibility IN ('public', 'friends')")

    op.add_column("user_music_profiles", sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"))
    op.create_index("ix_user_music_profiles_visibility", "user_music_profiles", ["visibility"])
    op.create_check_constraint("ck_music_identity_visibility", "user_music_profiles", "visibility IN ('private', 'friends', 'public')")
    op.execute("UPDATE user_music_profiles SET visibility = CASE WHEN is_public THEN 'public' ELSE 'private' END")

    op.create_table(
        "friend_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("receiver_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receiver_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sender_id", "receiver_id", name="uq_friend_request_pair"),
        sa.CheckConstraint("sender_id <> receiver_id", name="ck_friend_request_not_self"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'cancelled')", name="ck_friend_request_status"),
    )
    op.create_index("ix_friend_requests_sender_id", "friend_requests", ["sender_id"])
    op.create_index("ix_friend_requests_receiver_id", "friend_requests", ["receiver_id"])
    op.create_index("ix_friend_requests_status", "friend_requests", ["status"])

    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_a_id", sa.Integer(), nullable=False),
        sa.Column("user_b_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_a_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_b_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_a_id", "user_b_id", name="uq_friendship_pair"),
        sa.CheckConstraint("user_a_id < user_b_id", name="ck_friendship_ordered_pair"),
    )
    op.create_index("ix_friendships_user_a_id", "friendships", ["user_a_id"])
    op.create_index("ix_friendships_user_b_id", "friendships", ["user_b_id"])

    op.create_table(
        "user_blocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("blocker_id", sa.Integer(), nullable=False),
        sa.Column("blocked_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_block_pair"),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_user_block_not_self"),
    )
    op.create_index("ix_user_blocks_blocker_id", "user_blocks", ["blocker_id"])
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])

    op.create_table(
        "social_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("target_type IN ('user', 'post', 'comment')", name="ck_social_report_target"),
    )
    op.create_index("ix_social_reports_reporter_id", "social_reports", ["reporter_id"])
    op.create_index("ix_social_reports_target_id", "social_reports", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_social_reports_target_id", table_name="social_reports")
    op.drop_index("ix_social_reports_reporter_id", table_name="social_reports")
    op.drop_table("social_reports")
    op.drop_index("ix_user_blocks_blocked_id", table_name="user_blocks")
    op.drop_index("ix_user_blocks_blocker_id", table_name="user_blocks")
    op.drop_table("user_blocks")
    op.drop_index("ix_friendships_user_b_id", table_name="friendships")
    op.drop_index("ix_friendships_user_a_id", table_name="friendships")
    op.drop_table("friendships")
    op.drop_index("ix_friend_requests_status", table_name="friend_requests")
    op.drop_index("ix_friend_requests_receiver_id", table_name="friend_requests")
    op.drop_index("ix_friend_requests_sender_id", table_name="friend_requests")
    op.drop_table("friend_requests")

    op.drop_constraint("ck_music_identity_visibility", "user_music_profiles", type_="check")
    op.drop_index("ix_user_music_profiles_visibility", table_name="user_music_profiles")
    op.drop_column("user_music_profiles", "visibility")

    op.drop_constraint("ck_forum_post_visibility", "forum_posts", type_="check")
    op.drop_constraint("ck_forum_post_kind", "forum_posts", type_="check")
    op.drop_constraint("fk_forum_posts_mix_id", "forum_posts", type_="foreignkey")
    op.drop_index("ix_forum_posts_mix_id", table_name="forum_posts")
    op.drop_index("ix_forum_posts_visibility", table_name="forum_posts")
    op.drop_index("ix_forum_posts_kind", table_name="forum_posts")
    op.drop_column("forum_posts", "mix_id")
    op.drop_column("forum_posts", "visibility")
    op.drop_column("forum_posts", "kind")
