"""
friendship.py

This file defines the friendships table.

A friendship starts as a request from one user (the requester) to
another (the addressee) and moves through a small state machine:

    pending -> accepted
    pending -> declined

Why one row per relationship instead of two?
Storing a single directional row (requester_id -> addressee_id) is enough:
once status="accepted", the relationship is symmetric in how the app
reads it (see friend_service.py), so we never need a second mirrored row.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Friendship(Base):
    """
    SQLAlchemy model for the friendships table.
    """

    __tablename__ = "friendships"

    __table_args__ = (
        UniqueConstraint(
            "requester_id",
            "addressee_id",
            name="uq_friendships_requester_addressee",
        ),
        CheckConstraint(
            "requester_id <> addressee_id",
            name="ck_friendships_no_self_request",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined')",
            name="ck_friendships_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    # The user who sent the friend request.
    requester_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The user who received the friend request.
    addressee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # One of: "pending", "accepted", "declined".
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # Set when the addressee accepts or declines. Null while pending.
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
