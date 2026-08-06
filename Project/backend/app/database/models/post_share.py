"""
post_share.py

This file defines the post_shares table.

A share is a simple counter, not a repost: recording that a given user
shared a given post at least once. The (post_id, user_id) unique
constraint means re-clicking "share" is a no-op rather than inflating
the count.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PostShare(Base):
    """
    SQLAlchemy model for the post_shares table.
    """

    __tablename__ = "post_shares"

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_post_shares_post_user"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
