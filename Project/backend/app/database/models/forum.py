"""Public forum posts, comments, and one-vote-per-user engagement."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.core.time import utc_now


class ForumPost(Base):
    __tablename__ = "forum_posts"
    __table_args__ = (
        CheckConstraint("kind IN ('discussion', 'status', 'mix_share')", name="ck_forum_post_kind"),
        CheckConstraint("visibility IN ('public', 'friends')", name="ck_forum_post_visibility"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="discussion", index=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public", index=True)
    mix_id: Mapped[int | None] = mapped_column(ForeignKey("mixes.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)


class ForumComment(Base):
    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Null for a top-level comment; set for a reply. Single-level only by
    # convention (routers/forum.py rejects replying to a reply) even though
    # the self-referential FK itself would allow deeper nesting -- see
    # create_comment's docstring.
    parent_comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("forum_comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)


class ForumPostVote(Base):
    __tablename__ = "forum_post_votes"
    __table_args__ = (CheckConstraint("value IN (-1, 1)", name="ck_forum_post_vote_value"),)

    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ForumCommentVote(Base):
    __tablename__ = "forum_comment_votes"
    __table_args__ = (CheckConstraint("value IN (-1, 1)", name="ck_forum_comment_vote_value"),)

    comment_id: Mapped[int] = mapped_column(ForeignKey("forum_comments.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
