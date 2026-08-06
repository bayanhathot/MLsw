"""
mix.py

This file defines the mixes and mix_segments tables.

A Mix is the persisted result of running a prompt through Audius search
(see services/mix_service.py). It always belongs to exactly one Post
(see post.py) - there is no independent "save a mix without posting it"
flow yet.

MixSegment mirrors the ephemeral MixSegment shape already used by the
ungrouped MVP endpoint in routers/mixes.py (that router is intentionally
left untouched - see its docstring).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Mix(Base):
    """
    SQLAlchemy model for the mixes table.
    """

    __tablename__ = "mixes"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    # The user whose prompt generated this mix.
    creator_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The original vibe prompt, kept for provenance/display.
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # Ordered list of tracks that make up this mix.
    segments: Mapped[list["MixSegment"]] = relationship(
        "MixSegment",
        order_by="MixSegment.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MixSegment(Base):
    """
    SQLAlchemy model for the mix_segments table.

    One row per track in a mix's playback queue.
    """

    __tablename__ = "mix_segments"

    __table_args__ = (
        UniqueConstraint("mix_id", "position", name="uq_mix_segments_mix_position"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    mix_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mixes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 1-based order within the mix.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    audio_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    start_second: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_second: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_to_next: Mapped[str] = mapped_column(
        String(30), nullable=False, default="crossfade"
    )

    # Where this track came from (currently always "audius") and its id there.
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(100), nullable=False)
