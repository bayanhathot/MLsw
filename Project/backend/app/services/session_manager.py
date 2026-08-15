"""Persistent, deterministic AI-DJ session behavior.

A DJSession persists a live SessionState: the current (feedback-mutated)
PromptIntent, which CandidateRetriever resolved it, and the resulting
now-playing/reasoning data. The real-time coaching feature ("more energy" /
"less vocals" / "smoother") mutates that stored intent using the same
deterministic keyword rules it always used, then re-runs the pipeline
against whichever CandidateRetriever originally served this session -- so it
works the same whether that retriever is the local catalog or Audius.
"""

import os
import time
from threading import Lock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.session import DJSession, SessionFeedback, UserPreference
from app.schemas import (
    NowPlayingRead,
    PromptIntent,
    ReasoningRead,
    SelectedSegment,
    SessionRead,
    Track,
)
from app.services.pipeline.dependencies import get_vibe_understander
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)
from app.services.pipeline.orchestrator import NoMatchingCandidate, retrieve_candidates_with_fallback
from app.services.pipeline_debug_service import notify_pipeline_debug_change
from app.services import session_candidate_pool

# How many recently-played tracks a session remembers to avoid immediately
# repeating one when advancing (requirement: continuous playback should work
# through a candidate pool, not loop the same track back-to-back). Capped so
# this never grows unbounded across a long-running session.
_PLAYED_TRACK_HISTORY = 10

# How many ranked candidates _resolve_and_render asks a CandidateRetriever
# for. Deliberately larger than _PLAYED_TRACK_HISTORY: the exclude-scan
# below needs real fresh alternatives to fall through to once a session has
# played a few tracks, not just the exact number it's trying to avoid
# repeating. CatalogTrackRetriever (only ~4 seed rows) just returns fewer
# than this, same as it always has -- retrieve()'s contract has never
# guaranteed exactly `limit` results.
_CANDIDATE_LIMIT = 15

# Below this many still-fresh (not in exclude_track_keys) candidates, a hit
# on session_candidate_pool is treated as too thin to keep serving from --
# a real retrieval refreshes the pool instead of letting advance() grind
# down to repeats before the next natural refresh (a fingerprint change).
_CANDIDATE_POOL_REFRESH_THRESHOLD = 3

# How long a prepare_next() result stays eligible for advance_session's fast
# path (PHASE_C_PREFETCH_DESIGN.md section 3.3). Short-ish on purpose: this
# only needs to bridge the gap between "prepared ahead of time" and "the
# current track actually ends" -- not act as a general-purpose cache.
PREPARED_NEXT_TTL_SECONDS = float(os.getenv("PREPARED_NEXT_TTL_SECONDS", "300"))

# How many ranked candidates _resolve_and_render will actually try rendering
# before giving up and keeping the last (failed) attempt's pass-through --
# a track whose audio genuinely can't be fetched/decoded (AudioRenderer
# degrades to a pass-through pointing at a URL that's then often *also*
# broken for the listener, e.g. the source track being unavailable at the
# provider -- see RenderedAudio.fallback_reason) is skipped in favor of the
# next-ranked candidate instead of stopping the resolution there. Capped so
# a systemically broken source can't turn one resolution into a string of
# slow, doomed download attempts (each up to
# audio_renderer._REMOTE_TIMEOUT_SECONDS).
AUDIO_RENDER_RETRY_LIMIT = int(os.getenv("AUDIO_RENDER_RETRY_LIMIT", "3"))

COVER_URL = "/brand/zonix-logo.svg"

_ENERGY_LEVELS = ["low", "medium", "high"]
_VOCALS_LEVELS = ["less", "neutral", "more"]

# Same descriptive copy the old hardcoded TRACKS dict used for each mood
# bucket; anything outside those 4 seeded buckets (an upload, an Audius
# track) gets a generic role label instead.
_ROLE_BY_BUCKET = {
    "energy": "Energy lift",
    "vocals": "Vocal center",
    "focus": "Low-distraction flow",
    "smooth": "Balanced opener",
}


def _normalize_feedback(feedback: str) -> str:
    value = feedback.strip().lower().replace(" ", "_")
    if "energy" in value:
        return "more_energy"
    if "vocal" in value:
        return "less_vocals"
    if "smooth" in value:
        return "smoother"
    if "good" in value or "like" in value:
        # Praise reinforces whatever is actually playing, rather than
        # teaching a generic preference that may contradict the session's
        # own context.
        return "reinforce"
    return "custom"


def _mutate_intent(intent: PromptIntent, normalized: str) -> tuple[PromptIntent, bool]:
    """Applies one coaching command to `intent`, using the same blunt jump
    the old track_key swap used (not a gradual nudge), so "more energy"
    reliably lands on the same kind of candidate every time. Returns the
    (possibly unchanged) intent and whether the planner should prefer a
    smoother transition."""

    data = intent.model_dump()
    if normalized == "more_energy":
        data["energy"] = "high"
    elif normalized == "less_vocals":
        data["energy"] = "low"
        data["vocals"] = "less"
    elif normalized == "smoother":
        return intent, True
    else:
        return intent, False
    return PromptIntent.model_validate(data), False


def _apply_preference(intent: PromptIntent, feedback: str) -> PromptIntent | None:
    """Turns one learned UserPreference row into an intent bias for a new
    session. Works purely in terms of Intent, so it applies no matter which
    CandidateRetriever ends up serving the biased intent (requirement 11)."""

    if feedback in ("more_energy", "less_vocals"):
        mutated, _ = _mutate_intent(intent, feedback)
        return mutated
    if feedback == "smoother":
        return intent  # "smooth" is already the deterministic default bucket
    if feedback.startswith("reinforce:"):
        parts = feedback.split(":", 2)
        if len(parts) == 3 and parts[1] in _ENERGY_LEVELS and parts[2] in _VOCALS_LEVELS:
            data = intent.model_dump()
            data["energy"], data["vocals"] = parts[1], parts[2]
            return PromptIntent.model_validate(data)
    return None


def _role_for(track: Track) -> str:
    return _ROLE_BY_BUCKET.get(track.vibe or "", "Now playing")


def _effective_original_intent(session: DJSession) -> dict:
    """original_intent_json is None on sessions created before this column
    existed -- intent_json (as of this resolution) is the best available
    stand-in for "the session's original intent" on those rows, rather than
    treating the absence as an error anywhere this gets read."""

    return session.original_intent_json or session.intent_json


def _fingerprint_as_json(fingerprint: session_candidate_pool.RetrievalFingerprint) -> list:
    """session_candidate_pool.fingerprint_for() returns a tuple (with a
    nested tuple of genres) for use as an in-memory dict key, but JSON has
    no tuple type -- prepared_next_json round-trips through a JSON column,
    so it stores and compares against this normalized list form instead,
    to avoid a `(...) != [...]` false mismatch after a save/load cycle."""

    artist, artist_mode, genres, mood, energy = fingerprint
    return [artist, artist_mode, list(genres), mood, energy]


def _prepared_expired(prepared: dict) -> bool:
    return time.monotonic() - prepared["prepared_at"] >= PREPARED_NEXT_TTL_SECONDS


def _prepared_is_valid(
    prepared: dict | None, fingerprint: session_candidate_pool.RetrievalFingerprint
) -> bool:
    """True only if `prepared` (session.prepared_next_json) exists, was
    resolved against the exact same retrieval fingerprint as `fingerprint`,
    and hasn't exceeded PREPARED_NEXT_TTL_SECONDS. prepare_next() uses this
    to decide whether it's a no-op; advance_session() uses it to decide
    whether to take the fast path (PHASE_C_PREFETCH_DESIGN.md section 3.3) --
    always re-derived from the session's *current* intent at the moment of
    the check, never trusted just because a prepared item exists."""

    if prepared is None:
        return False
    if prepared["fingerprint"] != _fingerprint_as_json(fingerprint):
        return False
    return not _prepared_expired(prepared)


# Per-session_id locks guarding prepare_next() so two near-simultaneous
# prepare calls for the same session don't both pay for a full
# retrieval/render. Not a correctness requirement -- session.prepared_next_json
# is a single side-slot where the last write just wins, so a race here is
# only ever wasted duplicate work, never corrupted state (see
# PHASE_C_PREFETCH_DESIGN.md section 3.5) -- but cheap to avoid. Same
# Lock-per-key idiom as session_candidate_pool.py's module-level lock.
_prepare_locks_guard = Lock()
_prepare_locks: dict[str, Lock] = {}


def _prepare_lock_for(session_id: str) -> Lock:
    with _prepare_locks_guard:
        lock = _prepare_locks.get(session_id)
        if lock is None:
            lock = Lock()
            _prepare_locks[session_id] = lock
        return lock


def _track_key(track: Track) -> str:
    return f"{track.source}:{track.source_track_id}"


def _selected_moment_text(segment: SelectedSegment) -> str:
    where = (
        "the track's detected chorus/hook"
        if segment.method == "chorus_detection"
        else "the full clip"
    )
    return (
        f"Selected {segment.track.title} by {segment.track.artist} "
        f"({segment.start_second}s-{segment.end_second}s, {where})."
    )


def _next_direction(session: DJSession) -> str:
    if session.selected_feedback:
        return f"Applied {session.selected_feedback}; the selected moment and next transition now reflect it."
    return "Give feedback to steer energy, vocals, or transition smoothness."


def _resolve_and_render(
    db: Session,
    intent: PromptIntent,
    retriever: CandidateRetriever,
    fallback_retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
    *,
    session_id: str,
    previous_segment: SelectedSegment | None,
    prefers_smoother: bool,
    exclude_track_keys: frozenset[str] = frozenset(),
    recent_artists: frozenset[str] = frozenset(),
) -> tuple[Track, SelectedSegment, dict, dict, dict, CandidateRetriever]:
    """Runs CandidateRetriever -> SegmentSelector -> TransitionPlanner ->
    AudioRenderer for one session-sized (single track) resolution and
    returns the pieces needed to persist SessionState, plus a pipeline_trace
    dict recording which concrete implementation handled each of those four
    stages and a short result from each -- read by the internal debug panel
    (routers/debug.py). The caller fills in the vibe_understander stage,
    since understand() may or may not have been called this resolution
    (feedback re-resolves without a new LLM call).

    `retriever` is tried first; `fallback_retriever` only runs when
    `retriever` plainly finds nothing (e.g. Audius is unreachable, or its
    search for a named artist comes back empty) -- never a substitute for
    "found something, but the user already heard it". `exclude_track_keys`
    skips already-played candidates within whichever retriever's results
    actually came back, so a session can advance through a real candidate
    pool instead of replaying the same top match; if every candidate is
    excluded, the top match plays again rather than raising, since "loop
    indefinitely" is the point once a
    session's pool is exhausted. `recent_artists` is a softer signal than
    exclude_track_keys -- a ranking-capable retriever penalizes (doesn't
    filter) a candidate whose artist is in it, so it can still surface as a
    fallback rather than disappearing outright. Raises NoMatchingCandidate
    only when both retrievers come back empty.

    Before running a real retrieval, checks session_candidate_pool for a
    pool already ranked under `intent`'s current fingerprint. A hit is only
    used if it still has more than _CANDIDATE_POOL_REFRESH_THRESHOLD
    not-yet-excluded candidates left -- an almost-exhausted pool triggers a
    real refresh instead of grinding down to repeats before the fingerprint
    (and so the cache key) next changes. Because the fingerprint only covers
    the fields that actually affect retrieval/ranking (see
    session_candidate_pool.fingerprint_for), any resolution whose intent
    genuinely changed -- every feedback mutation that matters, since energy
    is part of the fingerprint and is the one field every current mutation
    path touches -- naturally misses and forces a fresh retrieval; nothing
    here has to special-case "was this feedback-driven" to get that right.

    Rendering itself can still fail per-track (the source audio genuinely
    unavailable/undecodable, e.g. Audius returning a 4xx for that specific
    track) even though retrieval/ranking succeeded -- see
    AUDIO_RENDER_RETRY_LIMIT: rather than accepting the first candidate's
    failed pass-through, up to that many ranked candidates are tried before
    giving up and keeping the last attempt.
    """

    fingerprint = session_candidate_pool.fingerprint_for(intent)
    cached_candidates = session_candidate_pool.get(session_id, fingerprint)
    candidate_pool_reused = False
    if cached_candidates is not None:
        fresh_count = sum(
            1 for candidate in cached_candidates if _track_key(candidate) not in exclude_track_keys
        )
        if fresh_count >= _CANDIDATE_POOL_REFRESH_THRESHOLD:
            candidates = cached_candidates
            # served_by wasn't cached (session_candidate_pool only stores
            # the ranked tracks) -- reconstructed from which source the
            # cached tracks actually carry, so `fell_back`/`name`/
            # `implementation` below stay accurate rather than assuming the
            # primary retriever served a pool that was really the catalog
            # fallback's.
            served_by = fallback_retriever if candidates[0].source == "catalog" else retriever
            candidate_pool_reused = True

    if not candidate_pool_reused:
        candidates, served_by = retrieve_candidates_with_fallback(
            db, intent, retriever, fallback_retriever, limit=_CANDIDATE_LIMIT, recent_artists=recent_artists
        )
        session_candidate_pool.put(session_id, fingerprint, candidates)
    fresh_candidates = [
        candidate for candidate in candidates if _track_key(candidate) not in exclude_track_keys
    ] or candidates

    # Try candidates in ranked order until one actually renders, rather than
    # settling for the first candidate's pass-through if its audio couldn't
    # be fetched/decoded. skipped_tracks -- surfaced in the pipeline debug
    # trace below -- records what was tried and discarded along the way, so
    # a "why did it play something odd" question is answerable without
    # backend logs. Skipped candidates are never marked "played" (they
    # never played), so they remain eligible on a future resolution too.
    skipped_tracks: list[dict] = []
    attempts = fresh_candidates[:AUDIO_RENDER_RETRY_LIMIT]
    for index, candidate in enumerate(attempts):
        track = candidate
        segment = selector.select(db, track)
        transition = planner.plan(previous_segment, segment, prefers_smoother=prefers_smoother)
        rendered = renderer.render([segment], [transition])
        # Stop -- and keep this attempt, whatever it is -- once it succeeds,
        # or once the retry budget is spent: the last attempt is always the
        # final result, even a failed one, never itself recorded as
        # "skipped" (that label is only for a candidate discarded in favor
        # of a different one that was tried next).
        if not rendered.is_pass_through or index == len(attempts) - 1:
            break
        skipped_tracks.append({
            "source": track.source,
            "source_track_id": track.source_track_id,
            "title": track.title,
            "fallback_reason": rendered.fallback_reason,
        })

    now_playing = {
        "title": track.title,
        "artist": track.artist,
        "album": track.album or "Zonix catalog",
        "cover_url": track.cover_url or COVER_URL,
        "role": _role_for(track),
        "audio_url": rendered.audio_url,
        "segment": segment.model_dump(mode="json"),
    }
    reasoning = {
        "selectedMoment": _selected_moment_text(segment),
        "transitionPlan": transition.notes,
    }
    # Both best-effort only: neither CatalogTrackRetriever nor the
    # single-query Audius retriever compute a score breakdown, and only the
    # two Audius retrievers make any search_tracks calls at all -- both are
    # None/missing whenever `served_by` doesn't expose the attribute. On a
    # candidate_pool_reused hit, `served_by` didn't actually run this
    # resolution (it's reconstructed from cached track sources above), so
    # its last_candidate_scores/last_cache_hit instance state reflects
    # whatever *other* call last touched that singleton, not this
    # resolution -- reading them here would show misleading, unrelated
    # data, so both are explicitly None instead.
    score_breakdown = (
        None if candidate_pool_reused
        else getattr(served_by, "last_candidate_scores", {}).get(_track_key(track))
    )
    cache_hit = None if candidate_pool_reused else getattr(served_by, "last_cache_hit", None)
    pipeline_trace = {
        "candidate_retriever": {
            "implementation": type(served_by).__name__,
            "name": served_by.name,
            "fell_back": served_by is not retriever,
            "candidate_count": len(candidates),
            "candidate_pool_reused": candidate_pool_reused,
            "selected_track": {
                "source": track.source,
                "source_track_id": track.source_track_id,
                "title": track.title,
                "artist": track.artist,
            },
            "score_breakdown": score_breakdown,
            "cache_hit": cache_hit,
        },
        "segment_selector": {
            "implementation": type(selector).__name__,
            "method": segment.method,
            "start_second": segment.start_second,
            "end_second": segment.end_second,
            "bpm": segment.bpm,
            "musical_key": segment.musical_key,
        },
        "transition_planner": {
            "implementation": type(planner).__name__,
            "crossfade_ms": transition.crossfade_ms,
            "style": transition.style,
            "notes": transition.notes,
        },
        "audio_renderer": {
            "implementation": type(renderer).__name__,
            "is_pass_through": rendered.is_pass_through,
            "offset_count": len(rendered.offsets),
            # The URL actually handed to the player, and -- when
            # is_pass_through is True -- why: surfaced so a "won't play"
            # report is diagnosable straight from the debug panel (was it
            # our own /media/renders/... file, or a raw external stream URL
            # that never got rendered at all, and if the latter, did the
            # download or the decode fail).
            "resolved_audio_url": rendered.audio_url,
            "fallback_reason": rendered.fallback_reason,
            # Candidates tried and discarded before landing on `track`
            # (empty when the first candidate rendered fine) -- see
            # AUDIO_RENDER_RETRY_LIMIT.
            "skipped_tracks": skipped_tracks,
        },
        "resolved_at": utc_now().isoformat(),
    }
    return track, segment, now_playing, reasoning, pipeline_trace, served_by


def serialize_session(session: DJSession) -> SessionRead:
    now_playing = session.now_playing_json
    reasoning = session.reasoning_json
    return SessionRead(
        id=session.id,
        prompt=session.prompt,
        status=session.status,
        vibeLabel=session.vibe_label,
        audioUrl=now_playing["audio_url"],
        nowPlaying=NowPlayingRead(
            title=now_playing["title"],
            artist=now_playing["artist"],
            album=now_playing["album"],
            coverUrl=now_playing["cover_url"],
            vibeLabel=session.vibe_label,
            role=now_playing["role"],
        ),
        reasoning=ReasoningRead(
            selectedMoment=reasoning["selectedMoment"],
            transitionPlan=reasoning["transitionPlan"],
            nextDirection=_next_direction(session),
        ),
        selectedFeedback=session.selected_feedback,
    )


def _initial_intent(
    prompt: str, db: Session, user_id: int | None, vibe: VibeUnderstander
) -> PromptIntent:
    intent = vibe.understand(prompt)
    is_neutral = intent.energy == "medium" and intent.vocals == "neutral" and not intent.artist
    if is_neutral and user_id is not None:
        preferences = (
            db.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.score > 0)
            .order_by(UserPreference.score.desc(), UserPreference.count.desc())
            .all()
        )
        for preference in preferences:
            biased = _apply_preference(intent, preference.feedback)
            if biased is not None:
                return biased
    return intent


def create_session(
    db: Session,
    prompt: str,
    user_id: int | None,
    *,
    vibe: VibeUnderstander,
    retriever: CandidateRetriever,
    fallback_retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> SessionRead:
    intent = _initial_intent(prompt, db, user_id, vibe)
    # Generated up front (not left to the DJSession constructor below) so
    # _resolve_and_render can key session_candidate_pool by this session's
    # real, final id from its very first resolution -- a brand-new id has
    # never been cached, so this always falls through to a real retrieval
    # and populates the pool for the first advance() to reuse.
    session_id = f"session_{uuid4().hex}"
    track, _, now_playing, reasoning, pipeline_trace, served_by = _resolve_and_render(
        db, intent, retriever, fallback_retriever, selector, planner, renderer,
        session_id=session_id, previous_segment=None, prefers_smoother=False,
    )
    pipeline_trace["vibe_understander"] = {
        "implementation": type(vibe).__name__,
        "invoked": True,
        "intent": intent.model_dump(mode="json"),
        # Current == original at creation time, by definition.
        "original_intent": intent.model_dump(mode="json"),
    }

    session = DJSession(
        id=session_id,
        user_id=user_id,
        prompt=prompt,
        status="playing",
        vibe_label=now_playing["segment"]["track"]["vibe_label"] or "Balanced opener",
        retriever_name=served_by.name,
        intent_json=intent.model_dump(mode="json"),
        original_intent_json=intent.model_dump(mode="json"),
        now_playing_json=now_playing,
        reasoning_json=reasoning,
        pipeline_trace_json=pipeline_trace,
        played_track_keys_json=[_track_key(track)],
        played_artists_json=[track.artist],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    notify_pipeline_debug_change()
    return serialize_session(session)


def get_session(db: Session, session_id: str) -> DJSession | None:
    return db.query(DJSession).filter(DJSession.id == session_id).first()


def apply_feedback(
    db: Session,
    session: DJSession,
    feedback: str,
    *,
    retriever: CandidateRetriever,
    fallback_retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> SessionRead:
    current_intent = PromptIntent.model_validate(session.intent_json)
    normalized = _normalize_feedback(feedback)
    session.selected_feedback = feedback
    db.add(
        SessionFeedback(
            session_id=session.id,
            user_id=session.user_id,
            feedback=feedback,
            normalized_feedback=normalized,
        )
    )

    preference_key: str | None = None
    if normalized in ("more_energy", "less_vocals", "smoother"):
        mutated, prefers_smoother = _mutate_intent(current_intent, normalized)
        preference_key = normalized
    elif normalized == "reinforce":
        mutated, prefers_smoother = current_intent, False
        preference_key = f"reinforce:{current_intent.energy}:{current_intent.vocals}"
    else:
        mutated, prefers_smoother = current_intent, False

    resolved_again = False
    if mutated is not current_intent or prefers_smoother:
        # Always try Audius-then-catalog fresh, rather than trusting
        # session.retriever_name as a pinned choice: if Audius genuinely has
        # nothing for this intent, that stays true on every re-resolution
        # (feedback only mutates energy/vocals, never the artist/query), so
        # this naturally keeps re-falling through to the catalog exactly
        # when the original resolution needed to -- and recovers gracefully
        # if Audius was down at creation but is back by the time feedback
        # runs, or vice versa.
        previous_segment = SelectedSegment.model_validate(session.now_playing_json["segment"])
        recent_artists = frozenset(session.played_artists_json or [])
        try:
            track, _, now_playing, reasoning, pipeline_trace, served_by = _resolve_and_render(
                db, mutated, retriever, fallback_retriever, selector, planner, renderer,
                session_id=session.id, previous_segment=previous_segment,
                prefers_smoother=prefers_smoother, recent_artists=recent_artists,
            )
            # Feedback mutates the stored intent with fixed keyword rules
            # (_mutate_intent) rather than calling the LLM again -- invoked
            # stays False so the debug panel doesn't imply a call that never
            # happened, while still naming which implementation is bound.
            pipeline_trace["vibe_understander"] = {
                "implementation": type(get_vibe_understander()).__name__,
                "invoked": False,
                "intent": mutated.model_dump(mode="json"),
                # Read before intent_json is reassigned below -- apply_feedback
                # never writes to original_intent_json, only intent_json mutates.
                "original_intent": _effective_original_intent(session),
            }
            session.intent_json = mutated.model_dump(mode="json")
            if mutated is not current_intent:
                # PHASE_C_PREFETCH_DESIGN.md section 3.4: any prepared next
                # item was resolved against the intent this just replaced --
                # advance_session's own fingerprint check (section 3.3) would
                # already refuse to serve it, but clearing it here too means
                # it doesn't linger unused in the row. Gated on the intent
                # actually changing (not just prefers_smoother alone, which
                # leaves the fingerprint unchanged), matching the spec's own
                # "MORE ENERGY -> discard the prepared next item" example.
                session.prepared_next_json = None
            session.now_playing_json = now_playing
            session.reasoning_json = reasoning
            session.pipeline_trace_json = pipeline_trace
            session.retriever_name = served_by.name
            session.vibe_label = now_playing["segment"]["track"]["vibe_label"] or session.vibe_label
            session.played_track_keys_json = (
                (session.played_track_keys_json or []) + [_track_key(track)]
            )[-_PLAYED_TRACK_HISTORY:]
            session.played_artists_json = (
                (session.played_artists_json or []) + [track.artist]
            )[-_PLAYED_TRACK_HISTORY:]
            resolved_again = True
        except NoMatchingCandidate:
            # Nothing matched the mutated intent closely enough; keep the
            # session on its current track rather than erroring out a live
            # session over one bad feedback mutation.
            pass

    if session.user_id is not None and preference_key is not None:
        preference = (
            db.query(UserPreference)
            .filter_by(user_id=session.user_id, feedback=preference_key)
            .first()
        )
        if preference is None:
            preference = UserPreference(
                user_id=session.user_id, feedback=preference_key, count=0, score=0
            )
            db.add(preference)
        preference.count += 1
        preference.score += 1

    db.commit()
    db.refresh(session)
    if resolved_again:
        notify_pipeline_debug_change()
    return serialize_session(session)


def advance_session(
    db: Session,
    session: DJSession,
    *,
    retriever: CandidateRetriever,
    fallback_retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> SessionRead:
    """Continues a still-playing session onto the next track/segment
    matching its current (unmutated) intent once the current one finishes --
    the continuous, no-input-required loop this pipeline was built around.
    Called automatically by the frontend on media-ended, not by user action,
    so it never mutates intent the way feedback does; it only rotates
    through the same candidate pool feedback would use, skipping whatever
    the session already played recently so it doesn't immediately repeat.

    Explicit coaching feedback (apply_feedback) still wins if the two race:
    both are ordinary commits to the same DJSession row, so whichever
    request's commit lands last is what persists -- no special locking
    needed, same as any other concurrent write to one row.

    PHASE_C_PREFETCH_DESIGN.md section 3.3: if prepare_next() already parked
    a still-valid result for this exact intent, that's applied directly
    instead -- no retrieve/select/plan/render at all. The prepared item is
    re-validated against the session's *current* intent fingerprint right
    here, not trusted just because it exists, since feedback may have
    mutated the intent after it was prepared but before this call landed."""

    intent = PromptIntent.model_validate(session.intent_json)
    fingerprint = session_candidate_pool.fingerprint_for(intent)
    prepared = session.prepared_next_json
    if _prepared_is_valid(prepared, fingerprint):
        pipeline_trace = prepared["pipeline_trace"]
        pipeline_trace["vibe_understander"] = {
            "implementation": type(get_vibe_understander()).__name__,
            "invoked": False,
            "intent": intent.model_dump(mode="json"),
            "original_intent": _effective_original_intent(session),
        }
        session.now_playing_json = prepared["now_playing"]
        session.reasoning_json = prepared["reasoning"]
        session.pipeline_trace_json = pipeline_trace
        session.retriever_name = pipeline_trace["candidate_retriever"]["name"]
        session.vibe_label = (
            prepared["now_playing"]["segment"]["track"]["vibe_label"] or session.vibe_label
        )
        session.played_track_keys_json = (
            (session.played_track_keys_json or []) + [prepared["track_key"]]
        )[-_PLAYED_TRACK_HISTORY:]
        session.played_artists_json = (
            (session.played_artists_json or []) + [prepared["artist"]]
        )[-_PLAYED_TRACK_HISTORY:]
        session.prepared_next_json = None
        db.commit()
        db.refresh(session)
        notify_pipeline_debug_change()
        return serialize_session(session)

    previous_segment = SelectedSegment.model_validate(session.now_playing_json["segment"])
    exclude = frozenset(session.played_track_keys_json or [])
    recent_artists = frozenset(session.played_artists_json or [])
    try:
        track, _, now_playing, reasoning, pipeline_trace, served_by = _resolve_and_render(
            db, intent, retriever, fallback_retriever, selector, planner, renderer,
            session_id=session.id, previous_segment=previous_segment, prefers_smoother=False,
            exclude_track_keys=exclude, recent_artists=recent_artists,
        )
    except NoMatchingCandidate:
        # Nothing to advance to (e.g. Audius briefly unreachable); leave the
        # session on its current track rather than ending it outright.
        return serialize_session(session)

    pipeline_trace["vibe_understander"] = {
        "implementation": type(get_vibe_understander()).__name__,
        "invoked": False,
        "intent": intent.model_dump(mode="json"),
        # advance_session never mutates intent, so this is unchanged from
        # whatever apply_feedback last wrote (or the true original, if
        # feedback was never used this session).
        "original_intent": _effective_original_intent(session),
    }
    session.now_playing_json = now_playing
    session.reasoning_json = reasoning
    session.pipeline_trace_json = pipeline_trace
    session.retriever_name = served_by.name
    session.vibe_label = now_playing["segment"]["track"]["vibe_label"] or session.vibe_label
    session.played_track_keys_json = (
        (session.played_track_keys_json or []) + [_track_key(track)]
    )[-_PLAYED_TRACK_HISTORY:]
    session.played_artists_json = (
        (session.played_artists_json or []) + [track.artist]
    )[-_PLAYED_TRACK_HISTORY:]

    db.commit()
    db.refresh(session)
    notify_pipeline_debug_change()
    return serialize_session(session)


def prepare_next(
    db: Session,
    session: DJSession,
    *,
    retriever: CandidateRetriever,
    fallback_retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> None:
    """PHASE_C_PREFETCH_DESIGN.md section 3.2: runs the exact same resolution
    advance_session() would do, ahead of time, and parks the result in
    session.prepared_next_json instead of the live now_playing_json/
    reasoning_json/pipeline_trace fields -- nothing this session currently
    reports as playing is touched. A no-op if the session isn't
    `"playing"`, or if a still-valid (unexpired, current-fingerprint)
    prepared item already exists.

    Guarded by a per-session Lock so two near-simultaneous calls for the
    same session don't both pay for a full retrieval/render -- see the
    module-level _prepare_locks comment for why this is a latency nicety,
    not a correctness requirement (section 3.5).

    A different race matters more: stop_session() or apply_feedback()
    (the branch that clears prepared_next_json on intent mutation) can
    commit *while* this function's own retrieval/render work is still
    running. Without a re-check, this function's eventual write would land
    afterward and silently resurrect a prepared item on a session that was
    just stopped, or whose intent just changed -- so right before writing,
    the session's current state is re-fetched and re-validated against the
    fingerprint this resolution actually ran against, and the result is
    discarded (not written) if either no longer matches. This is a normal,
    expected outcome of the race, not an error."""

    if session.status != "playing":
        return

    lock = _prepare_lock_for(session.id)
    if not lock.acquire(blocking=False):
        # Another prepare_next() call for this session is already doing the
        # real work; its result (or lack of one) is what matters, not a
        # second redundant attempt.
        return
    try:
        intent = PromptIntent.model_validate(session.intent_json)
        fingerprint = session_candidate_pool.fingerprint_for(intent)
        if _prepared_is_valid(session.prepared_next_json, fingerprint):
            return

        previous_segment = SelectedSegment.model_validate(session.now_playing_json["segment"])
        exclude = frozenset(session.played_track_keys_json or [])
        recent_artists = frozenset(session.played_artists_json or [])
        try:
            track, _, now_playing, reasoning, pipeline_trace, _served_by = _resolve_and_render(
                db, intent, retriever, fallback_retriever, selector, planner, renderer,
                session_id=session.id, previous_segment=previous_segment, prefers_smoother=False,
                exclude_track_keys=exclude, recent_artists=recent_artists,
            )
        except NoMatchingCandidate:
            # Nothing to prepare ahead of time; advance_session falls back to
            # its own real resolution when it's actually called, same as it
            # always has.
            return

        # Re-fetch and re-validate right before writing: stop_session() or
        # apply_feedback() may have committed while the retrieval/render
        # work above was in flight. db.refresh() picks up whatever is
        # actually committed now, not whatever this function saw when it
        # started -- a plain re-check of the in-memory `session` object
        # wouldn't catch a change made through a different Session/request.
        db.refresh(session)
        current_intent = PromptIntent.model_validate(session.intent_json)
        current_fingerprint = session_candidate_pool.fingerprint_for(current_intent)
        if session.status != "playing" or current_fingerprint != fingerprint:
            return

        session.prepared_next_json = {
            "track_key": _track_key(track),
            "artist": track.artist,
            "now_playing": now_playing,
            "reasoning": reasoning,
            # vibe_understander is deliberately absent here -- advance_session
            # fills it in at consume time, exactly like every other caller of
            # _resolve_and_render already does with its own pipeline_trace.
            "pipeline_trace": pipeline_trace,
            "fingerprint": _fingerprint_as_json(fingerprint),
            "prepared_at": time.monotonic(),
        }
        db.commit()
    finally:
        lock.release()


def stop_session(db: Session, session: DJSession) -> dict:
    session.status = "stopped"
    session.prepared_next_json = None
    db.commit()
    return {"session_id": session.id, "status": "stopped", "message": "AI DJ session stopped."}
