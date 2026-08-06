"""
post.py

This file defines the posts table.

A Post is a feed entry: one user sharing one mix, with a short
description. Posts are the only thing shown in the feed - there is no
separate "text post" type.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Post(Base):
    """
    SQLAlchemy model for the posts table.
    """

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    author_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # One mix belongs to exactly one post - a mix is always created
    # together with the post that shares it (see mix_service.create_mix).
    mix_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mixes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    mix: Mapped["Mix"] = relationship("Mix")
    author: Mapped["User"] = relationship("User")
