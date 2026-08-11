"""Persisted generated mixes and their ordered segments."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.core.time import utc_now


class Mix(Base):
    __tablename__ = "mixes"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="ck_mix_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner = relationship("User", back_populates="mixes")
    segments: Mapped[list["MixSegment"]] = relationship(
        "MixSegment",
        back_populates="mix",
        order_by="MixSegment.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MixSegment(Base):
    __tablename__ = "mix_segments"
    __table_args__ = (UniqueConstraint("mix_id", "position", name="uq_mix_segment_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mix_id: Mapped[int] = mapped_column(
        ForeignKey("mixes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_second: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_second: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_to_next: Mapped[str] = mapped_column(String(50), nullable=False, default="crossfade")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(255), nullable=False)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vibe: Mapped[str | None] = mapped_column(String(100), nullable=True)

    mix = relationship("Mix", back_populates="segments")
