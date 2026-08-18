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
        CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_catalog_track_visibility",
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
    # "private" (owner-only) vs "public" (anyone) -- "friends" deliberately
    # deferred until something concretely needs the friendship-graph join
    # (see ai-dj-segment-metadata-architecture.md §12.2). Enforced at
    # retrieval/streaming time (see catalog_retriever._visibility_filter and
    # routers/catalog.py's audio/cover endpoints); a fresh upload defaults to
    # "public" so the catalog grows the AI-DJ's shared pool by default --
    # uploaders who want a track kept to themselves choose "private" per
    # upload.
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public", index=True)

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
    # Optional cover art (jpg/png/webp), stored under UPLOAD_DIR/catalog_covers
    # the same way storage_name lives under UPLOAD_DIR/catalog -- null falls
    # back to the app's existing initials-placeholder UI, never a fabricated
    # image or an external fetch.
    cover_storage_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Computed by upload_queue.py's worker for every upload already; this
    # column just stops it from being discarded. Indexed both for a fast
    # duplicate-file lookup and because routers/catalog.py's dedup policy
    # (reuse an existing row's storage/analysis for byte-identical audio,
    # see _find_duplicate_by_checksum) queries it on every upload.
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Filled in by the one-time BPM/key/best-segment analysis job.
    analysis_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    segment_start_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_end_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Which build of the analysis pipeline produced the fields above ("v1" =
    # the current librosa chroma+beat_track+self-similarity approach, see
    # audio_analysis.py's module docstring) and when it ran -- both null
    # until analysis actually completes (never set on a "failed" run, so a
    # failed row's null version/timestamp naturally falls into any future
    # "reprocess" query without needing its own separate condition). Stored
    # independently, not derived from one another: targeted reprocessing
    # will want "everything below version N" and "everything analyzed
    # before date X" as two different queries, not one computed from the
    # other. String, matching this codebase's other versioned fields
    # (user_music_profiles.dna_version, ColdSeedRun.version) rather than a
    # bare integer.
    analysis_version: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
