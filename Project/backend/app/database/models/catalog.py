"""The real, swappable local track catalog behind CandidateRetriever.

This table replaces the old hardcoded 4-track Python dict. It starts seeded
with those same 4 demo rows (migration data insert) and grows as users upload
tracks through POST /catalog/tracks. `artist` carries a Postgres pg_trgm GIN
index so CandidateRetriever can fuzzy-match a user-named artist against real
rows instead of a fixed list.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.database.base import Base


class CatalogTrack(Base):
    __tablename__ = "catalog_tracks"
    __table_args__ = (
        CheckConstraint(
            "analysis_status IN ('pending', 'completed', 'failed', 'not_applicable')",
            name="ck_catalog_track_analysis_status",
        ),
        CheckConstraint(
            "segment_method IS NULL OR segment_method IN ('chorus_detection', 'whole_clip')",
            name="ck_catalog_track_segment_method",
        ),
        Index(
            "ix_catalog_tracks_artist_trgm",
            "artist",
            postgresql_using="gin",
            postgresql_ops={"artist": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Null for the seeded demo catalog; set for user-uploaded tracks.
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Only set on the 4 seeded rows; drives the legacy energy/vocals/focus/smooth
    # keyword matching when the prompt names no specific artist.
    mood_bucket: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    vibe_label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Not unique: the 4 seeded demo rows deliberately share one physical
    # file, the same way the old TRACKS dict pointed every bucket at
    # cuemix-demo.wav. Uploaded tracks always get a fresh uuid4-based name
    # from upload_queue.py regardless.
    storage_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Filled in by the one-time BPM/key/best-segment analysis job.
    analysis_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    segment_start_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_end_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
