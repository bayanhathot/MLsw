"""Persistent, provider-keyed analysis cache for externally-sourced tracks
(Audius today; `source` leaves room for another provider later without a
schema change).

Deliberately NOT a catalog_tracks row (see the proposal doc's own
rationale, cuemix-persistent-audius-analysis-proposal.md §4): nobody
uploaded this track into Cuemix, Cuemix never owns its audio long-term, and
it must never become catalog-primary-retrievable just by being cached --
see catalog_retriever.py (untouched by this table) and
pipeline/external_track_cache.py (the only writer/reader of this table).

Mirrors catalog_tracks' analysis-field shape closely on purpose (same
bpm/key/loudness/beat-grid/segment columns, same analysis_status value
set) so SegmentSelector/TransitionPlanner/AudioRenderer can treat an
enriched external Track identically to a catalog Track once analysis
completes -- see LibrosaSegmentSelector.select()'s external_track_id
branch. segment_start_second/segment_end_second/segment_method ARE
included here (not computed live at request time): CatalogTrack persists
a locked segment window chosen once by audio_analysis._best_segment, and
LibrosaSegmentSelector.select() reads it back verbatim rather than
recomputing anything from stored chroma/beat data at request time -- this
table mirrors that same locked-window shape, not a live-compute one.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.database.base import Base


class ExternalTrack(Base):
    __tablename__ = "external_tracks"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_external_tracks_source_external_id"),
        # Same value set catalog_tracks' analysis_status CHECK uses (see
        # CatalogTrack.__table_args__) -- reused as-is rather than a second,
        # parallel enum: "not_applicable" is never written for an external
        # track today (there is no seeded-external-track case, unlike
        # catalog_tracks' 4 demo rows), but keeping the identical value set
        # means one shared mental model and one shared CHECK definition
        # style across both tables.
        CheckConstraint(
            "analysis_status IN ('pending', 'completed', 'failed', 'not_applicable')",
            name="ck_external_track_analysis_status",
        ),
        CheckConstraint(
            "segment_method IS NULL OR segment_method IN ('chorus_detection', 'whole_clip')",
            name="ck_external_track_segment_method",
        ),
        Index("ix_external_tracks_source_external_id", "source", "external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Provider identity (see this module's own docstring) -- the normal
    # lookup key, checkable without ever downloading audio. "audius" is the
    # only value written today.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Provider metadata, captured at first-encounter time purely for
    # identity/debugging -- NOT the source of truth for a runtime Track's
    # display fields (those always come fresh from the retriever's own live
    # query, e.g. audius_retriever._to_track; a provider-side title/artist
    # edit should never require re-analysis to show up).
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Integrity, not identity (see this module's own docstring) -- SHA-256
    # over the exact temporary-audio bytes analyze_audio() last ran
    # against. Compared against a fresh download's own hash whenever a live
    # playback/render path already fetches the complete file for another
    # reason (pipeline.external_track_cache.verify_fingerprint) -- never a
    # separate network request purely to check this.
    audio_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    analysis_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    analysis_version: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # How many analysis attempts have ever been made for this row (success
    # or failure) -- gates re-enqueueing a repeatedly-failing track past
    # external_track_cache._EXTERNAL_ANALYSIS_MAX_ATTEMPTS. catalog_tracks
    # has no equivalent counter/cap: analyze_catalog_track never
    # auto-retries a *failed* row at all (requeue_pending_analysis only
    # ever re-dispatches still-"pending" rows, stranded by a crash) -- so
    # there is no existing cap/backoff policy to reuse here, unlike this
    # column's neighbors. See external_track_cache.py's own module
    # docstring.
    analysis_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_last_failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set (never cleared) the moment a fingerprint mismatch is detected
    # (pipeline.external_track_cache.verify_fingerprint) -- the cached
    # analysis fields are deliberately left untouched at that point (only
    # this flag flips), so a request already mid-flight against the old
    # data isn't disrupted; every field beneath it stays exactly as last
    # analyzed until a fresh analyze_external_track() run overwrites all of
    # them together, atomically, at commit time. A "completed" row is only
    # ever trusted (see LibrosaSegmentSelector.select()) when this is also
    # False.
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    # None until verify_fingerprint's first real check of this row; a
    # mismatch does not update this (see is_stale's own docstring) -- a
    # match is the only thing that ever advances it, so "how long has this
    # actually been confirmed still-current" stays answerable.
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Same shape/meaning as CatalogTrack's identically-named columns -- see
    # catalog.py for each field's own derivation docstring; not repeated
    # here since both tables are populated by the exact same
    # audio_analysis.analyze_audio() core.
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bpm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    key_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    camelot: Mapped[str | None] = mapped_column(String(4), nullable=True)
    key_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    integrated_loudness_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    beat_grid_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    downbeat_grid_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    phrase_boundaries_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    segment_start_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_end_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
