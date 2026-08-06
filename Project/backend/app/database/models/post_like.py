"""
post_like.py

This file defines the post_likes table.

A like is a pure membership fact - a user either likes a post or does
not. The (post_id, user_id) pair is the primary key, so "did this user
like this post" is a simple existence check and there is no way to
double-like.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PostLike(Base):
    """
    SQLAlchemy model for the post_likes table.
    """

    __tablename__ = "post_likes"

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
