"""
play_event.py

This file defines the play_events table: one row per "tick" of real
listening time, reported by the frontend player.

Why track per-segment rather than per-mix or per-post?
minutes_listened and favorite_artists (see services/profile_service.py)
are computed on demand by summing/grouping these rows - segment-level
granularity is what lets favorite_artists join through to
MixSegment.artist without needing a separate denormalized column
anywhere.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PlayEvent(Base):
    """
    SQLAlchemy model for the play_events table.
    """

    __tablename__ = "play_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mix_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mixes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    segment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mix_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional context: which post the listen happened through. Kept
    # even if the post is later deleted (SET NULL), since the listening
    # history itself should still count toward stats.
    post_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("posts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    seconds_listened: Mapped[int] = mapped_column(Integer, nullable=False)

    # One of: "heartbeat", "pause", "ended", "unmount".
    client_event_type: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
