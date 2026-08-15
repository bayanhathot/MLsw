"""Persistent AI-DJ session and feedback models."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.core.time import utc_now


class DJSession(Base):
    """Persists a live SessionState: the mutated Intent plus whichever
    CandidateRetriever/segment/transition it currently resolves to."""

    __tablename__ = "dj_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('playing', 'stopped')", name="ck_dj_session_status"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="playing")
    vibe_label: Mapped[str] = mapped_column(String(100), nullable=False)
    # Name of whichever CandidateRetriever actually served the current
    # track ("catalog", or whichever Audius retriever name is configured --
    # e.g. "audius_multi_query", see AUDIUS_RETRIEVER in
    # pipeline/dependencies.py) -- informational, not pinned: every
    # resolution tries Audius first and falls through to the catalog only
    # when Audius finds nothing, so this can change from one resolution to
    # the next (see session_manager._resolve_and_render).
    retriever_name: Mapped[str] = mapped_column(String(40), nullable=False)
    # The current, feedback-mutated PromptIntent for this session.
    intent_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # The session's initial PromptIntent, set once at creation and never
    # touched again by apply_feedback/advance_session (unlike intent_json,
    # which mutates) -- internal debugging state only (see
    # session_manager._effective_original_intent for how rows created
    # before this column existed fall back to intent_json instead of
    # erroring), not a public API field.
    original_intent_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # A fully pre-resolved "next" resolution (track key, now_playing,
    # reasoning, pipeline_trace, retrieval fingerprint, prepared_at) parked
    # by session_manager.prepare_next() ahead of when it's actually needed --
    # never applied to the live now_playing_json/reasoning_json/intent_json
    # fields directly (see PHASE_C_PREFETCH_DESIGN.md section 3.5 for why
    # that separation is what makes this race-safe). advance_session()
    # consumes it only if its fingerprint still matches the session's
    # current intent and it hasn't exceeded PREPARED_NEXT_TTL_SECONDS.
    prepared_next_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Serialized NowPlayingRead-shaped data for the current track/segment.
    now_playing_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Serialized ReasoningRead-shaped data (selectedMoment/transitionPlan/nextDirection).
    reasoning_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Per-stage debug trace (implementation name + short result) for the most
    # recent pipeline resolution -- read by the internal debug panel
    # (routers/debug.py); never read by the ordinary session flow, so it's
    # nullable and safe to leave unset on older rows.
    pipeline_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Composite "source:source_track_id" keys of recently-played tracks
    # (capped, see session_manager._PLAYED_TRACK_HISTORY), so continuous
    # advancing doesn't immediately repeat whatever just played.
    played_track_keys_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Artist names of recently-played tracks, appended in lockstep with
    # played_track_keys_json (same _PLAYED_TRACK_HISTORY cap) -- read as
    # recent_artists by CandidateRetriever.retrieve() so the ranker can
    # penalize repeating an artist without needing to look up each played
    # track's artist from played_track_keys_json after the fact.
    played_artists_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    selected_feedback: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    feedback_events: Mapped[list["SessionFeedback"]] = relationship(
        "SessionFeedback", cascade="all, delete-orphan", passive_deletes=True
    )


class SessionFeedback(Base):
    __tablename__ = "session_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("dj_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    feedback: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_feedback: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class KnownBrokenTrack(Base):
    """A track whose audio AudioRenderer has recently failed to
    fetch/decode, recorded so a fresh session doesn't have to rediscover
    the same failure by actually attempting the download again (see
    session_manager._resolve_and_render / services/known_broken_tracks.py).
    Always has an expiry, enforced by the service layer's TTL check, never
    treated as a permanent blacklist -- provider-side availability (e.g. an
    Audius 403) can change."""

    __tablename__ = "known_broken_tracks"

    # Matches session_manager._track_key(track): f"{track.source}:{track.source_track_id}"
    track_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    fallback_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    feedback: Mapped[str] = mapped_column(String(40), primary_key=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class PromptShortcut(Base):
    """A logged-in user's own repeated prompt *intent*, clustered by a
    normalized signature (mood + energy + vocals + genres + whether an
    artist was required) rather than exact text -- see
    services/prompt_shortcuts.py's signature_for(). Once a signature has
    been seen enough times (PROMPT_SHORTCUT_MIN_USES), it's eligible to
    replace a static preset chip in PromptComposer.svelte with the user's
    own most-recent phrasing for that intent."""

    __tablename__ = "prompt_shortcuts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    signature: Mapped[str] = mapped_column(String(160), primary_key=True)
    # The representative prompt text shown/reused as the chip's label and
    # fill-in text -- overwritten with the most-recent prompt seen for this
    # signature on every match, so it stays current with how the user
    # actually phrases this intent today.
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )
