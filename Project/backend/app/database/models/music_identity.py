"""Listening history and Music Identity persistence.

Raw listening events are intentionally stored separately from derived metrics.
This lets Cuemix recompute analytics and future ML features without losing the
original behavioral signal.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.database.base import Base


class UserMusicProfile(Base):
    __tablename__ = "user_music_profiles"
    __table_args__ = (CheckConstraint("visibility IN ('private', 'friends', 'public')", name="ck_music_identity_visibility"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    # Listening analytics are private unless the owner explicitly opts in.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private", index=True)

    # Future ML/algorithm output contract. These stay empty until the later ML phase.
    dna_status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_generated")
    dna_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dna_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dna_features: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    dna_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dna_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class ListeningEvent(Base):
    __tablename__ = "listening_events"
    __table_args__ = (
        UniqueConstraint("client_event_id", name="uq_listening_event_client_id"),
        CheckConstraint("seconds_listened >= 0", name="ck_listening_seconds_nonnegative"),
        CheckConstraint(
            "completion_ratio IS NULL OR (completion_ratio >= 0 AND completion_ratio <= 1)",
            name="ck_listening_completion_ratio",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("dj_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mix_id: Mapped[int | None] = mapped_column(
        ForeignKey("mixes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("mix_segments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(255), nullable=False)
    track_title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    vibe: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seconds_listened: Mapped[int] = mapped_column(Integer, nullable=False)
    track_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_start_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_end_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
