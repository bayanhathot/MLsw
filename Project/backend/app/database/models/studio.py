"""User-owned Studio segments and bounded passive-behavior signals."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.database.base import Base


class SavedSegment(Base):
    """A reusable, exact moment from a canonical catalog/provider track."""

    __tablename__ = "saved_segments"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('catalog', 'audius')",
            name="ck_saved_segment_source_type",
        ),
        CheckConstraint(
            "created_from IN ('manual', 'ai', 'auto')",
            name="ck_saved_segment_created_from",
        ),
        CheckConstraint(
            "start_ms >= 0 AND start_ms < end_ms AND end_ms <= track_duration_ms",
            name="ck_saved_segment_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vibe: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    created_from: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    analysis_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bpm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    key_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    camelot: Mapped[str | None] = mapped_column(String(4), nullable=True)
    key_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    integrated_loudness_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    phrase_boundaries_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="saved_segments")


class StudioBehaviorEvent(Base):
    """A stable, bounded ranking signal; raw events stay auditable."""

    __tablename__ = "studio_behavior_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('segment_save', 'segment_replay', 'early_skip', 'mix_like')",
            name="ck_studio_behavior_event_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    saved_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_segments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mix_id: Mapped[int | None] = mapped_column(
        ForeignKey("mixes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    user = relationship("User", back_populates="studio_behavior_events")
    saved_segment = relationship("SavedSegment")
