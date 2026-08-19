"""The real, swappable local track catalog behind CandidateRetriever.

This table replaces the old hardcoded 4-track Python dict. It starts seeded
with those same 4 demo rows (migration data insert) and grows as users upload
tracks through POST /catalog/tracks. `artist` carries a Postgres pg_trgm GIN
index so CandidateRetriever can fuzzy-match a user-named artist against real
rows instead of a fixed list.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
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
    # A genuine confidence signal read off the same onset-strength
    # autocorrelation beat_track uses internally to choose bpm -- not an
    # invented number (see audio_analysis._bpm_confidence's docstring for
    # the derivation). Normalized to [0.0, 1.0]: 1.0 means the chosen
    # tempo's periodicity dominated essentially every analyzed window;
    # values near 0.0 mean it was rarely the dominant periodicity, i.e. a
    # genuinely weak/ambiguous beat.
    bpm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # "major" or "minor" -- the mode half of real Krumhansl-Schmuckler-style
    # key-finding (see audio_analysis._estimate_key); musical_key alone was
    # always just a bare pitch class with no mode until this was added.
    # Null under the exact same conditions musical_key is (not yet
    # analyzed, analysis failed, or a seeded demo row -- see this column's
    # neighbors).
    key_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Camelot wheel notation (e.g. "8B" for C major), a deterministic
    # lookup from (musical_key, key_mode) -- see audio_analysis.camelot_for
    # and its _CAMELOT_MAJOR/_CAMELOT_MINOR tables. Stored rather than
    # computed on read since it's a pure function of two already-stored
    # columns and every consumer wants it pre-joined with the row. Null
    # whenever musical_key/key_mode are.
    camelot: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # The correlation margin between the winning Krumhansl-Schmuckler key
    # template and its runner-up (see audio_analysis._estimate_key),
    # covering the *whole* (musical_key, key_mode) decision -- not a
    # separate confidence for pitch class vs. mode. Normalized to [0.0,
    # 1.0]: 0.0 means the winning and runner-up templates fit the observed
    # chroma equally well (maximally ambiguous -- often the same root's
    # opposite mode, or a closely related key), 1.0 means the runner-up
    # was a far worse fit. This superseded an earlier, narrower
    # chroma-energy-margin definition of the same column name (only ever
    # covered pitch-class choice, no mode) -- both real signals, never an
    # invented number.
    key_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ITU-R BS.1770 integrated loudness of the whole analyzed waveform, in
    # LUFS (measured once here via pyloudnorm, reusing the same waveform
    # librosa already loaded for bpm/key -- never re-measured per segment
    # or per crossfade at render time, which would answer a subtly
    # different question and cost real CPU on every render). Typically
    # negative (louder audio -> a value closer to 0, e.g. -8; quieter ->
    # more negative, e.g. -20). Null exactly when bpm/musical_key are: not
    # yet analyzed, analysis failed, or the seeded demo catalog rows that
    # never ran real analysis (see analysis_status="not_applicable").
    # audio_renderer.py skips loudness normalization entirely when this is
    # null -- an Audius track (no catalog_track_id at all) always hits
    # that same path, matching bpm/musical_key's existing None-means-skip
    # handling in transition_planner.py.
    integrated_loudness_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Beat-grid timing, in seconds, straight from librosa.beat.beat_track's
    # own beat-frame output (already computed to derive bpm -- see
    # audio_analysis._beat_grids; never a second onset-envelope pass).
    # Small JSON lists on the row, mirroring played_track_keys_json/
    # played_artists_json's existing small-list-JSON pattern (DJSession)
    # rather than a new table -- these lists are only ever read whole,
    # never queried/filtered by individual entry. `[]` (not null) means
    # analysis ran and genuinely found no beats; null means not yet
    # analyzed/failed/not_applicable, same as every other analysis field.
    beat_grid_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Every _BEATS_PER_BAR-th entry of beat_grid_json, starting from the
    # first beat -- a COARSE HEURISTIC assuming constant 4/4 time, not
    # genuine downbeat/meter detection (librosa's beat_track has no
    # concept of bar position at all). Drifts on a 3/4 track or one with a
    # meter change partway through.
    downbeat_grid_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Every _BARS_PER_PHRASE-th entry of downbeat_grid_json -- an even
    # coarser heuristic layered on top of the already-heuristic
    # downbeat_grid_json (assumes fixed 8-bar phrasing), not real
    # structural/section analysis.
    phrase_boundaries_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    segment_start_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_end_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Which build of the analysis pipeline produced the fields above ("v2" =
    # the current librosa chroma+beat_track+self-similarity approach plus
    # real Krumhansl-Schmuckler key-finding, see audio_analysis.py's module
    # docstring and ANALYSIS_VERSION's own comment) and when it ran -- both null
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
