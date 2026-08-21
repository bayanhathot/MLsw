"""Persistent, deterministic AI-DJ session behavior.

A DJSession persists a live SessionState: the current (feedback-mutated)
PromptIntent, which CandidateRetriever resolved it, and the resulting
now-playing/reasoning data. The real-time coaching feature ("more energy" /
"less vocals" / "smoother") mutates that stored intent using the same
deterministic keyword rules it always used, then re-runs the pipeline
against whichever CandidateRetriever originally served this session -- so it
works the same whether that retriever is the local catalog or Audius.
"""

import json
import logging
import os
import time
from threading import Lock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.session import DJSession, SessionFeedback, UserPreference
from app.schemas import (
    AutoMixMode,
    BridgeRender,
    NowPlayingRead,
    PromptIntent,
    ReasoningRead,
    SelectedSegment,
    SessionRead,
    StagedRender,
    Track,
)
from app.services import (
    known_broken_tracks,
    prompt_shortcuts,
    session_candidate_pool,
    upload_queue,
)
from app.services.admin_debug_events import publish_session_updated, record_event
from app.services.pipeline import audio_renderer, external_track_cache
from app.services.pipeline.catalog_retriever import (
    LAST_RESORT_CATALOG_RETRIEVER,
    last_resort_tracks,
)
from app.services.pipeline.dependencies import get_vibe_understander
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)
from app.services.pipeline.orchestrator import (
    NoMatchingCandidate,
    retrieve_candidates,
    retrieve_candidates_with_fallback,
)
from app.services.pipeline.transition_planner import MAX_CROSSFADE_MS
from app.services.pipeline_debug_service import notify_pipeline_debug_change
from app.services.prompt_parser import apply_auto_mix_mode

logger = logging.getLogger(__name__)

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
# next-ranked candidate instead of stopping the resolution there. Defaults to
# the full _CANDIDATE_LIMIT -- a session should exhaust every real candidate
# it already retrieved from Audius before ever landing on a pass-through, not
# give up after an arbitrary handful of them while untried real alternatives
# still sit in the ranked pool (session-pipeline requests already get their
# own longer client-side timeout for exactly this kind of case -- see
# frontend/src/lib/services/sessionApi.js). Still env-overridable as a
# safety cap in case
# _CANDIDATE_LIMIT is ever raised well past what one request's latency
# budget can absorb (each attempt costs up to
# audio_renderer.REMOTE_TIMEOUT_SECONDS +
# audio_renderer.LOCAL_AUDIO_OP_TIMEOUT_SECONDS -- see
# _MAX_SINGLE_ATTEMPT_SECONDS below).
AUDIO_RENDER_RETRY_LIMIT = int(
    os.getenv("AUDIO_RENDER_RETRY_LIMIT", str(_CANDIDATE_LIMIT))
)

# A wall-clock ceiling on how long one resolution spends retrying render
# attempts in total (the primary retriever's attempts plus any catalog
# rescue attempt combined -- see _resolve_and_render), independent of
# AUDIO_RENDER_RETRY_LIMIT's candidate-count cap: with that cap now
# defaulting to the whole candidate pool, a systemically broken source whose
# every attempt genuinely hangs (rather than failing fast with an HTTP error)
# must still not blow past the 45s client-side timeout session-pipeline
# calls get (frontend/src/lib/services/sessionApi.js), alongside whatever
# the VibeUnderstander/Ollama stage and retrieval already spent. Deliberately
# well under that 45s ceiling, not equal to it.
#
# §8's own batch measurement (scripts/measure_session_latency.py) found this
# budget wasn't actually being respected: it was only ever checked *between*
# candidate attempts inside _try_render_ranked_candidates, never *before*
# starting one, so a single slow attempt (an unbounded multi-hop redirect
# chain, or a stuck ffmpeg decode -- both now bounded, see
# audio_renderer._bounded) could blow past it by itself, and the loop would
# still go on to start further attempts afterward. See
# _MAX_SINGLE_ATTEMPT_SECONDS for the fix.
AUDIO_RENDER_TIME_BUDGET_SECONDS = float(
    os.getenv("AUDIO_RENDER_TIME_BUDGET_SECONDS", "25")
)

# The plausible fetch+decode critical-path cost of one candidate attempt --
# the two operations that must both complete, in sequence, before a
# candidate is even known to be viable (export happens afterward, only once
# a candidate already decoded successfully, and is fast/local -- not counted
# here). Used by _try_render_ranked_candidates to decide, *before* starting
# a new attempt, whether the shared deadline can plausibly still fit one --
# not the absolute worst case of every bounded operation in an attempt
# timing out simultaneously (render_bridge's own multiple export calls
# included), which would be so conservative it'd effectively disable retries
# under AUDIO_RENDER_TIME_BUDGET_SECONDS' own default.
_MAX_SINGLE_ATTEMPT_SECONDS = (
    audio_renderer.REMOTE_TIMEOUT_SECONDS
    + audio_renderer.LOCAL_AUDIO_OP_TIMEOUT_SECONDS
)

# How much of a selected segment's tail is carved off, blind, the instant
# the segment is chosen -- before any transition into a next track is even
# known -- so a real crossfade can later be blended into it without ever
# re-fetching or replaying audio (see this module's live-crossfade
# docstring further down, and DeterministicTransitionPlanner.plan()'s
# max_crossfade_ms docstring for how this reservation caps the crossfade
# actually rendered). Defaults to MAX_CROSSFADE_MS: under the planner's own
# clamp, no crossfade it would ever pick exceeds this, so the reservation
# is non-binding unless tuned independently.
RESERVED_TRANSITION_MS = int(os.getenv("RESERVED_TRANSITION_MS", str(MAX_CROSSFADE_MS)))

# §8 observability (measurement only -- see _log_stage_latency/prepare_next's
# own deadline-check log): the two real numbers prepare_next()'s own
# duration is worth comparing against, mirrored from the frontend rather
# than invented here. DJPlayerCard.svelte's maybePrepareNext() fires at
# Math.max(10, segmentLengthSeconds * 0.1) seconds of remaining playback --
# 10s is the worst-case (shortest) budget it would ever give this call
# (a longer segment gets more; the backend has no visibility into the
# frontend's actual playback position, so this is a conservative proxy,
# not an exact one). sessionApi.js's own client-side abort timeout for
# this call is the harder ceiling: past it, the frontend has already given
# up regardless of whether the backend eventually finishes.
_PREPARE_NEXT_MIN_FRONTEND_DEADLINE_MS = 10_000
_PREPARE_NEXT_CLIENT_TIMEOUT_MS = 20_000

COVER_URL = "/brand/cuemix-logo.svg"

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
        if (
            len(parts) == 3
            and parts[1] in _ENERGY_LEVELS
            and parts[2] in _VOCALS_LEVELS
        ):
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


def _fingerprint_as_json(
    fingerprint: session_candidate_pool.RetrievalFingerprint,
) -> list:
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


def _reserved_ms_for(segment: SelectedSegment) -> int:
    """Never reserves more than half of `segment`'s own duration -- a short
    segment (a tight chorus-detected window, or a brief upload) could
    otherwise have its entire body eaten by RESERVED_TRANSITION_MS, leaving
    nothing to actually play before the reserved window starts. This can
    push the eventual crossfade below MIN_CROSSFADE_MS via
    TransitionPlanner.plan()'s max_crossfade_ms -- see that method's
    docstring for why that's intentional."""

    duration_ms = max(0, (segment.end_second - segment.start_second) * 1000)
    return min(RESERVED_TRANSITION_MS, duration_ms // 2)


def _log_stage_latency(
    stage: str, session_id: str, started: float, pipeline_trace: dict | None
) -> None:
    """One structured INFO log line per create_session/apply_feedback/
    advance_session call -- §8 observability, measurement only (no
    alerting/dashboard here). Mirrors main.py's request_context
    middleware's own perf_counter() + json.dumps(...) idiom, the one
    existing "log how long X took" precedent in this codebase, rather
    than inventing a new one or adding a metrics dependency.

    `pipeline_trace` is whatever _resolve_and_render returned this call
    (already carries a `_timing` sub-dict: retrieval_ms/
    segment_selector_ms/transition_planner_ms/audio_renderer_ms/total_ms
    for that one resolution -- see that function) -- None whenever this
    call took a fast path (a bridge/reserved-tail promotion, a
    still-valid prepared item, feedback that didn't mutate the intent)
    and never actually called _resolve_and_render, in which case only
    this call's own total_ms/resolved=False are logged; there's no
    per-stage breakdown to report for work that didn't happen."""

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    entry = {
        "event": "session_stage_latency",
        "stage": stage,
        "session_id": session_id,
        "total_ms": duration_ms,
        "resolved": pipeline_trace is not None,
    }
    if pipeline_trace is not None:
        entry["resolution"] = pipeline_trace.get("_timing", {})
    logger.info(json.dumps(entry))
    record_event(entry)


def _staged_pass_through(rendered: object) -> tuple[bool, str | None]:
    """Reads (is_pass_through, fallback_reason) off whichever staged-render
    shape `rendered` actually is -- StagedTrackRender (a plain body render)
    exposes it on `.body`; BridgeRender exposes the equivalent on `.bridge`
    (its failure branch marks `.bridge`/`.next_body` identically, so
    `.bridge` alone is a faithful signal either way). Centralized so
    _try_render_ranked_candidates and _resolve_and_render's rescue path
    don't each need their own isinstance branch."""

    body = rendered.bridge if isinstance(rendered, BridgeRender) else rendered.body
    return body.is_pass_through, body.fallback_reason


def _promote(
    session: DJSession,
    *,
    now_playing: dict,
    reasoning: dict,
    pipeline_trace: dict,
    retriever_name: str,
    vibe_label: str | None,
    track_key: str | None = None,
    artist: str | None = None,
) -> None:
    """Shared bookkeeping applied every time a track (or a stage transition
    within one) becomes what a session actually reports as now-playing --
    previously duplicated ad hoc at each promotion site. Does not commit;
    the caller commits once, after any of its own additional field updates
    (e.g. apply_feedback's intent_json).

    `track_key`/`artist` are None for a promotion that doesn't represent a
    *new* logical track starting (a bridge finishing into its own body, or
    a reserved tail playing out verbatim) -- play history is only ever
    appended once per logical track, at the moment a fresh resolution or a
    body->bridge promotion first commits to it (a bridge already contains
    that track's audio), never again at a later stage transition within
    that same track's playback."""

    session.now_playing_json = now_playing
    session.reasoning_json = reasoning
    session.pipeline_trace_json = pipeline_trace
    session.retriever_name = retriever_name
    session.vibe_label = vibe_label or session.vibe_label
    if track_key is not None:
        session.played_track_keys_json = (
            (session.played_track_keys_json or []) + [track_key]
        )[-_PLAYED_TRACK_HISTORY:]
        session.played_artists_json = ((session.played_artists_json or []) + [artist])[
            -_PLAYED_TRACK_HISTORY:
        ]


def _delete_rendered_file(audio_url: str) -> None:
    """Deletes the on-disk render behind a now_playing-shaped `audio_url`,
    resolved the same way routers/media.py's /renders/{filename} route does
    (UPLOAD_DIR/renders/<filename>). Used by prepare_next()'s discard path
    (session_manager.py's own re-check found the session stopped or
    re-resolved while the render was still in flight): that path already
    never writes the DB record, but without this the file AudioRenderer
    already wrote to disk before the check would sit there as a permanent
    orphan -- _sweep_stale_renders' TTL sweep is a secondary safety net, not
    a substitute for cleaning up a render this process knows is unused right
    now. A pass-through `audio_url` (pointing straight at an external track
    URL because rendering failed) has no local file, so this is a no-op for
    those. Best-effort: a missing/already-swept file, or any other
    filesystem error, is not worth failing this request over."""

    marker = f"/{audio_renderer.RENDER_SUBDIR}/"
    if marker not in audio_url:
        return
    filename = audio_url.rsplit("/", 1)[-1]
    root = (upload_queue.UPLOAD_DIR / audio_renderer.RENDER_SUBDIR).resolve()
    path = (root / filename).resolve()
    if path.parent != root:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete discarded rendered file %s", path)


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


def _try_render_ranked_candidates(
    db: Session,
    candidates: list[Track],
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
    *,
    previous_segment: SelectedSegment | None,
    prefers_smoother: bool,
    deadline: float,
    resume_offset_ms: int = 0,
    bridge_from: StagedRender | None = None,
) -> tuple[Track, SelectedSegment, object, object, list[dict], dict]:
    """Filters `candidates` down to ones not already known-broken (recording
    the rest as skipped -- see known_broken_tracks.py), then tries what's
    left, in ranked order, until one renders for real, AUDIO_RENDER_RETRY_LIMIT
    is reached, or `deadline` (a time.monotonic() timestamp, shared across
    both this call and any later rescue call within the same resolution --
    see AUDIO_RENDER_TIME_BUDGET_SECONDS) passes -- whichever comes first.
    The last attempt tried is always kept as the result, even a failed
    pass-through. Every genuine render failure encountered here is
    persisted via known_broken_tracks.mark_broken so a later resolution --
    this session's or another's -- can skip it outright. `candidates` must
    be non-empty.

    Also returns stage_timings -- {"segment_selector_ms",
    "transition_planner_ms", "audio_renderer_ms"} -- summed across every
    attempt this call actually made (§8 observability): a retry that
    renders 3 candidates before one finally succeeds pays for all 3
    selector/planner/renderer calls, and that's real latency worth
    counting in full, not just the winning attempt's own cost.

    `bridge_from`, when given, means each candidate is tried as the *next*
    track of a live crossfade bridge out of an already-rendered reserved
    tail (renderer.render_bridge) rather than a plain standalone body
    (renderer.render_track_transition) -- see session_manager.py's
    live-crossfade docstring. `resume_offset_ms` only applies to the plain
    (non-bridge) path, for a track resuming after its own head already
    played as part of a bridge that led into it; a bridge candidate's own
    resume point is entirely decided by render_bridge's actual clamped
    crossfade, not this parameter. The two are mutually exclusive in
    practice (every real caller passes at most one), but nothing here
    enforces that -- it's true by construction of the call sites."""

    skipped_tracks: list[dict] = []
    known_broken_candidates, renderable_candidates = [], []
    for candidate in candidates:
        if known_broken_tracks.is_known_broken(db, _track_key(candidate)):
            known_broken_candidates.append(candidate)
        else:
            renderable_candidates.append(candidate)

    if renderable_candidates:
        for candidate in known_broken_candidates:
            skipped_tracks.append(
                {
                    "source": candidate.source,
                    "source_track_id": candidate.source_track_id,
                    "title": candidate.title,
                    "fallback_reason": "known_broken",
                }
            )
    else:
        # Every candidate is known-broken -- nothing left to skip *to*, so
        # fall through to actually trying them (same "loop rather than
        # raise once a pool is exhausted" rule exclude_track_keys already
        # follows in _resolve_and_render). Re-attempting also refreshes
        # each one's known-broken record either way.
        renderable_candidates = candidates

    stage_timings = {
        "segment_selector_ms": 0.0,
        "transition_planner_ms": 0.0,
        "audio_renderer_ms": 0.0,
    }
    attempts = renderable_candidates[:AUDIO_RENDER_RETRY_LIMIT]
    for index, candidate in enumerate(attempts):
        if index > 0 and deadline - time.monotonic() < _MAX_SINGLE_ATTEMPT_SECONDS:
            # §8's own batch measurement found the *only* existing deadline
            # check (at the bottom of this loop, below) ran *after* an
            # attempt already finished -- never stopped one from *starting*
            # that plainly couldn't fit in what was left. Every operation an
            # attempt can spend time on is now individually bounded (see
            # audio_renderer._bounded), so this check is finally meaningful:
            # not enough of the shared budget remains to plausibly get
            # through another attempt's fetch+decode critical path, so stop
            # here and let this resolution fall through to its existing
            # rescue/last-resort tiers (_resolve_and_render) instead of
            # starting an attempt destined to be abandoned anyway. The very
            # first attempt (index == 0) always runs regardless -- this
            # function must return *something* even if the deadline was
            # already tight before it started.
            skipped_tracks.append(
                {
                    "source": candidate.source,
                    "source_track_id": candidate.source_track_id,
                    "title": candidate.title,
                    "fallback_reason": "insufficient_time_remaining",
                }
            )
            break
        track = candidate
        selector_started = time.perf_counter()
        segment = selector.select(db, track)
        stage_timings["segment_selector_ms"] += (
            time.perf_counter() - selector_started
        ) * 1000

        # bridge_from.duration_ms is the previous track's already-rendered
        # reserved tail length -- a hard physical ceiling on how much audio
        # render_bridge can actually blend, applied here (not just inside
        # the renderer) so the descriptive transition.notes text and the
        # real render agree on the same crossfade_ms. The plain (non-bridge)
        # path passes no cap -- its `transition` here is purely descriptive
        # (render_track_transition never blends), matching today's behavior.
        max_crossfade_ms = bridge_from.duration_ms if bridge_from is not None else None
        planner_started = time.perf_counter()
        transition = planner.plan(
            previous_segment,
            segment,
            prefers_smoother=prefers_smoother,
            max_crossfade_ms=max_crossfade_ms,
        )
        stage_timings["transition_planner_ms"] += (
            time.perf_counter() - planner_started
        ) * 1000

        renderer_started = time.perf_counter()
        if bridge_from is None:
            rendered = renderer.render_track_transition(
                segment,
                resume_offset_ms=resume_offset_ms,
                reserved_ms=_reserved_ms_for(segment),
            )
        else:
            rendered = renderer.render_bridge(
                bridge_from,
                segment,
                crossfade_ms=transition.crossfade_ms,
                reserved_ms=_reserved_ms_for(segment),
            )
        stage_timings["audio_renderer_ms"] += (
            time.perf_counter() - renderer_started
        ) * 1000

        is_pass_through, fallback_reason = _staged_pass_through(rendered)
        if fallback_reason:
            # The failure itself is what's informative here, not which
            # retry slot it landed in -- even the final kept attempt (a
            # pass-through with no better alternative left) is worth
            # remembering, so the *next* resolution skips straight past it
            # instead of re-discovering the same dead end.
            known_broken_tracks.mark_broken(db, track, fallback_reason)
        # Stop -- and keep this attempt, whatever it is -- once it succeeds,
        # once the retry budget is spent, or once the shared time budget
        # runs out (most failures are fast HTTP errors, but a genuinely
        # unreachable host can still cost up to
        # audio_renderer.REMOTE_TIMEOUT_SECONDS +
        # audio_renderer.LOCAL_AUDIO_OP_TIMEOUT_SECONDS on one attempt, now
        # that both are actually bounded -- see _bounded): the last
        # attempt is always the final result, even a failed one, never
        # itself recorded as "skipped" (that label is only for a candidate
        # discarded in favor of a different one that was tried next).
        if (
            not is_pass_through
            or index == len(attempts) - 1
            or time.monotonic() >= deadline
        ):
            break
        skipped_tracks.append(
            {
                "source": track.source,
                "source_track_id": track.source_track_id,
                "title": track.title,
                "fallback_reason": fallback_reason,
            }
        )
    stage_timings = {key: round(value, 2) for key, value in stage_timings.items()}

    # Prompt 4: verify the winning attempt's fetched audio against its
    # cached external_tracks fingerprint, if any -- only ever using bytes
    # this same render already fetched (see StagedRender.audio_sha256's own
    # docstring), never a second network request. A no-op whenever `track`
    # was never cached (external_track_id unset) or nothing was actually
    # fetched (audio_sha256 unset -- a local_path load, or a pass-through).
    fetched_audio_sha256 = (
        rendered.body.audio_sha256
        if bridge_from is None
        else rendered.next_body.audio_sha256
    )
    external_track_cache.verify_fingerprint(db, track, fetched_audio_sha256)

    return track, segment, transition, rendered, skipped_tracks, stage_timings


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
    viewer_id: int | None = None,
    resume_offset_ms: int = 0,
    bridge_from: StagedRender | None = None,
) -> tuple[Track, SelectedSegment, dict, dict, dict, CandidateRetriever]:
    """Runs CandidateRetriever -> SegmentSelector -> TransitionPlanner ->
    AudioRenderer for one session-sized (single track) resolution and
    returns the pieces needed to persist SessionState, plus a pipeline_trace
    dict recording which concrete implementation handled each of those four
    stages and a short result from each -- read by the internal debug panel
    (routers/debug.py). The caller fills in the vibe_understander stage,
    since understand() may or may not have been called this resolution
    (feedback re-resolves without a new LLM call).

    `bridge_from`, when given, means this resolution is preparing a live
    crossfade bridge out of the session's current reserved tail rather than
    a standalone track (see this module's live-crossfade docstring further
    down) -- every candidate tried is rendered via renderer.render_bridge
    instead of render_track_transition, and the returned `now_playing`
    describes the bridge clip itself (`stage: "bridge"`), carrying the
    resolved next track's own pre-rendered body/tail alongside it so
    promoting past the bridge later needs no further computation.
    `resume_offset_ms` only applies to the non-bridge path (a track
    resuming after its own head already played as part of a bridge that
    led into it) -- ignored when `bridge_from` is given, since a bridge
    candidate's resume point is decided by the render itself.

    `retriever` (the local catalog) is tried first; `fallback_retriever`
    (Audius) only runs when `retriever` plainly finds nothing, or its own
    top match is too weak to trust (see
    orchestrator.retrieve_candidates_with_fallback /
    catalog_retriever.CATALOG_MATCH_THRESHOLD) -- never a substitute for
    "found something, but the user already heard it". If both come back
    empty, retrieve_candidates_with_fallback's own last-resort tier (any
    visible catalog row) still tries before this raises NoMatchingCandidate
    -- see that function's docstring for the full three-tier shape.
    `exclude_track_keys` skips already-played candidates within whichever
    retriever's results actually came back, so a session can advance
    through a real candidate pool instead of replaying the same top match;
    if every candidate is excluded, the top match plays again rather than
    raising, since "loop indefinitely" is the point once a session's pool
    is exhausted. `recent_artists` is a softer signal than
    exclude_track_keys -- a ranking-capable retriever penalizes (doesn't
    filter) a candidate whose artist is in it, so it can still surface as a
    fallback rather than disappearing outright.

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
    giving up and keeping the last attempt. If every one of those genuinely
    fails, whichever of {retriever, fallback_retriever} *didn't* serve this
    resolution gets one honest rescue attempt too (see
    _try_render_ranked_candidates) before this settles for a dead
    pass-through -- e.g. a named-artist search whose only Audius matches are
    all unavailable still lands on a real, playable (if less-matched)
    catalog track rather than silently "playing" nothing, and symmetrically
    a catalog track that somehow fails to render gets one Audius rescue
    attempt. No further rescue is attempted when the resolution already
    landed on the retrieval fallback chain's last-resort tier (there's
    nothing left to try).

    §8 observability (measurement only): pipeline_trace["_timing"] records
    how long each stage of *this* resolution actually took --
    retrieval_ms (the cache check, and any real retrieval it triggered),
    segment_selector_ms/transition_planner_ms/audio_renderer_ms (summed
    across every candidate attempt, primary plus any rescue -- see
    _try_render_ranked_candidates), and total_ms for the whole call.
    """

    resolve_started = time.perf_counter()
    retrieval_started = time.perf_counter()
    fingerprint = session_candidate_pool.fingerprint_for(intent)
    cached_candidates = session_candidate_pool.get(session_id, fingerprint)
    candidate_pool_reused = False
    if cached_candidates is not None:
        fresh_count = sum(
            1
            for candidate in cached_candidates
            if _track_key(candidate) not in exclude_track_keys
        )
        if fresh_count >= _CANDIDATE_POOL_REFRESH_THRESHOLD:
            candidates = cached_candidates
            # served_by wasn't cached (session_candidate_pool only stores
            # the ranked tracks) -- reconstructed from which source the
            # cached tracks actually carry, so `fell_back`/`name`/
            # `implementation` below stay accurate rather than assuming the
            # primary retriever served a pool that was really the Audius
            # fallback's. A catalog-sourced cached pool is assumed to be
            # `retriever` (the primary) even though a fresh resolution of
            # the same intent might have landed on
            # orchestrator.LAST_RESORT_CATALOG_RETRIEVER instead -- both are
            # catalog-sourced, and this reconstruction (like the rest of
            # this best-effort debug path) can't distinguish them from the
            # cached track alone.
            served_by = (
                retriever if candidates[0].source == "catalog" else fallback_retriever
            )
            candidate_pool_reused = True

    if not candidate_pool_reused:
        candidates, served_by = retrieve_candidates_with_fallback(
            db,
            intent,
            retriever,
            fallback_retriever,
            limit=_CANDIDATE_LIMIT,
            recent_artists=recent_artists,
            viewer_id=viewer_id,
        )
        session_candidate_pool.put(session_id, fingerprint, candidates)
    # Prompt 3: batched external_tracks cache lookup/dispatch for every
    # Audius candidate in `candidates` -- run on both the cache-hit and the
    # fresh-retrieval branch (idempotent either way: an already-enriched
    # Track just gets its external_track_id re-confirmed and last_seen_at
    # refreshed) so a cache-pool-reused resolution doesn't quietly skip
    # enrichment. Included inside this call's own retrieval_ms window (see
    # this function's own §8 observability docstring) so Prompt 6's
    # measurement honestly reflects this cost, not an artificially
    # excluded one. A first-line no-op when AUDIUS_ANALYSIS_CACHE_ENABLED
    # is False (see external_track_cache.py's own module docstring).
    external_track_cache.enrich_and_dispatch(db, candidates)
    fresh_candidates = [
        candidate
        for candidate in candidates
        if _track_key(candidate) not in exclude_track_keys
    ] or candidates
    retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 2)

    # Try candidates in ranked order until one actually renders, rather than
    # settling for the first candidate's pass-through if its audio couldn't
    # be fetched/decoded. skipped_tracks -- surfaced in the pipeline debug
    # trace below -- records what was tried and discarded along the way, so
    # a "why did it play something odd" question is answerable without
    # backend logs. Skipped candidates are never marked "played" (they
    # never played), so they remain eligible on a future resolution too.
    # render_deadline governs this call and any rescue call below together
    # (see AUDIO_RENDER_TIME_BUDGET_SECONDS) -- one shared budget for the
    # whole resolution's render attempts, not one per phase.
    render_deadline = time.monotonic() + AUDIO_RENDER_TIME_BUDGET_SECONDS
    track, segment, transition, rendered, skipped_tracks, stage_timings = (
        _try_render_ranked_candidates(
            db,
            fresh_candidates,
            selector,
            planner,
            renderer,
            previous_segment=previous_segment,
            prefers_smoother=prefers_smoother,
            deadline=render_deadline,
            resume_offset_ms=resume_offset_ms,
            bridge_from=bridge_from,
        )
    )

    # served_by's own candidates are all genuinely broken (not just
    # excluded/known-broken with nothing left to try) -- if there's a
    # *different* retriever we haven't consulted this resolution, give it
    # one honest shot before settling for a dead pass-through. A catalog
    # track (a local file -- see catalog_retriever.py -- never a remote
    # fetch) can turn a session that would otherwise land on unplayable
    # audio into one with a real, if less-matched, track -- and
    # symmetrically, if the catalog's own weak match was what served (and
    # somehow failed to render -- a corrupted local file), Audius gets the
    # same one honest shot. rescue_source is the one of {retriever,
    # fallback_retriever} that *didn't* serve; None when served_by is
    # neither (orchestrator.LAST_RESORT_CATALOG_RETRIEVER, already the
    # bottom of the retrieval fallback chain -- nothing left to try).
    # This rescue candidate list is never written to session_candidate_pool --
    # that cache's fingerprint/served_by-reconstruction semantics are for
    # the primary retrieval only, not a one-off audio-failure rescue. Skipped
    # entirely once render_deadline has already passed -- no budget left to
    # spend on a rescue attempt either.
    if served_by is retriever:
        rescue_source = fallback_retriever
    elif served_by is fallback_retriever:
        rescue_source = retriever
    else:
        rescue_source = None

    rendered_is_pass_through, rendered_fallback_reason = _staged_pass_through(rendered)
    if (
        rescue_source is not None
        and rendered_is_pass_through
        and time.monotonic() < render_deadline
    ):
        rescue_retrieval_started = time.perf_counter()
        try:
            rescue_candidates = retrieve_candidates(
                db,
                intent,
                rescue_source,
                limit=_CANDIDATE_LIMIT,
                recent_artists=recent_artists,
                viewer_id=viewer_id,
            )
        except NoMatchingCandidate:
            rescue_candidates = []
        retrieval_ms += round(
            (time.perf_counter() - rescue_retrieval_started) * 1000, 2
        )
        fresh_rescue_candidates = [
            candidate
            for candidate in rescue_candidates
            if _track_key(candidate) not in exclude_track_keys
        ]
        if fresh_rescue_candidates:
            (
                rescue_track,
                rescue_segment,
                rescue_transition,
                rescue_rendered,
                rescue_skipped,
                rescue_stage_timings,
            ) = _try_render_ranked_candidates(
                db,
                fresh_rescue_candidates,
                selector,
                planner,
                renderer,
                previous_segment=previous_segment,
                prefers_smoother=prefers_smoother,
                deadline=render_deadline,
                resume_offset_ms=resume_offset_ms,
                bridge_from=bridge_from,
            )
            for key, value in rescue_stage_timings.items():
                stage_timings[key] = round(stage_timings[key] + value, 2)
            rescue_is_pass_through, _rescue_fallback_reason = _staged_pass_through(
                rescue_rendered
            )
            if not rescue_is_pass_through:
                skipped_tracks.append(
                    {
                        "source": track.source,
                        "source_track_id": track.source_track_id,
                        "title": track.title,
                        "fallback_reason": rendered_fallback_reason,
                    }
                )
                skipped_tracks.extend(rescue_skipped)
                track, segment, transition, rendered = (
                    rescue_track,
                    rescue_segment,
                    rescue_transition,
                    rescue_rendered,
                )
                served_by = rescue_source

    # D1: primary plus the one rescue attempt above can both still end on a
    # pass-through -- a URL that was never actually rendered because the
    # source audio itself is unavailable/undecodable (e.g. Audius returning
    # 4xx for every remaining candidate). Serving that URL as "now playing"
    # means the player is handed dead audio. One more, last-ditch attempt:
    # the retrieval fallback chain's own tier-4 "any visible catalog row"
    # pool (orchestrator.retrieve_candidates_with_fallback /
    # LAST_RESORT_CATALOG_RETRIEVER), restricted to tracks not already tried
    # this resolution. Gated on `not intent.artist`, mirroring tier 4's own
    # gate there: an explicit artist ask must never be silently substituted
    # with an unrelated track just because the real match was unplayable --
    # that's a NoMatchingCandidate, not a consolation prize.
    still_pass_through, still_fallback_reason = _staged_pass_through(rendered)
    if still_pass_through and not intent.artist:
        tried_track_keys = (
            exclude_track_keys
            | {_track_key(track)}
            | {
                f"{entry['source']}:{entry['source_track_id']}"
                for entry in skipped_tracks
            }
        )
        last_resort_started = time.perf_counter()
        last_resort_candidates = [
            candidate
            for candidate in last_resort_tracks(
                db, viewer_id=viewer_id, limit=_CANDIDATE_LIMIT
            )
            if _track_key(candidate) not in tried_track_keys
        ]
        retrieval_ms += round((time.perf_counter() - last_resort_started) * 1000, 2)
        if last_resort_candidates:
            (
                lr_track,
                lr_segment,
                lr_transition,
                lr_rendered,
                lr_skipped,
                lr_stage_timings,
            ) = _try_render_ranked_candidates(
                db,
                last_resort_candidates,
                selector,
                planner,
                renderer,
                previous_segment=previous_segment,
                prefers_smoother=prefers_smoother,
                deadline=render_deadline,
                resume_offset_ms=resume_offset_ms,
                bridge_from=bridge_from,
            )
            for key, value in lr_stage_timings.items():
                stage_timings[key] = round(stage_timings[key] + value, 2)
            lr_is_pass_through, _lr_fallback_reason = _staged_pass_through(lr_rendered)
            if not lr_is_pass_through:
                skipped_tracks.append(
                    {
                        "source": track.source,
                        "source_track_id": track.source_track_id,
                        "title": track.title,
                        "fallback_reason": still_fallback_reason,
                    }
                )
                skipped_tracks.extend(lr_skipped)
                track, segment, transition, rendered = (
                    lr_track,
                    lr_segment,
                    lr_transition,
                    lr_rendered,
                )
                served_by = LAST_RESORT_CATALOG_RETRIEVER
        still_pass_through, still_fallback_reason = _staged_pass_through(rendered)

    if still_pass_through:
        # Every real candidate, the one rescue attempt, and (when eligible)
        # the last-resort catalog tier all failed to produce playable
        # audio -- refuse to serve a dead URL as now_playing. Recorded the
        # same way routers/sessions.py already records a create_session-time
        # NoMatchingCandidate, so this is visible in the admin debug event
        # feed regardless of which caller (create/apply_feedback/advance/
        # prepare_next) hit it -- those all already handle this exception
        # (see their own try/except NoMatchingCandidate blocks).
        record_event(
            {
                "event": "resolve_and_render_exhausted",
                "session_id": session_id,
                "last_attempted_track": {
                    "source": track.source,
                    "source_track_id": track.source_track_id,
                    "title": track.title,
                },
                "fallback_reason": still_fallback_reason,
            }
        )
        raise NoMatchingCandidate(
            "No playable audio could be rendered for this request: every ranked "
            "candidate, any rescue attempt from the other retriever, and (when "
            "eligible) the last-resort catalog fallback all failed to produce "
            "anything but an unavailable/undecodable source."
        )

    # bridge_from consistently determines rendered's shape across both the
    # primary and any rescue attempt above (rescue always reuses the same
    # bridge_from) -- so this one check is enough to know which of
    # StagedTrackRender/BridgeRender `rendered` actually is.
    if bridge_from is None:
        reserved_ms = (
            _reserved_ms_for(segment) if rendered.reserved_tail is not None else 0
        )
        now_playing = {
            "title": track.title,
            "artist": track.artist,
            "album": track.album or "Cuemix catalog",
            "cover_url": track.cover_url or COVER_URL,
            "role": _role_for(track),
            "audio_url": rendered.body.audio_url,
            "segment": segment.model_dump(mode="json"),
            "stage": "body",
            "resume_offset_ms": resume_offset_ms,
            "reserved_ms": reserved_ms,
            "tail_audio_url": rendered.reserved_tail.audio_url
            if rendered.reserved_tail
            else None,
        }
        renderer_is_pass_through = rendered.body.is_pass_through
        renderer_resolved_audio_url = rendered.body.audio_url
        renderer_fallback_reason = rendered.body.fallback_reason
    else:
        next_reserved_ms = (
            _reserved_ms_for(segment) if rendered.next_reserved_tail is not None else 0
        )
        now_playing = {
            "title": track.title,
            "artist": track.artist,
            "album": track.album or "Cuemix catalog",
            "cover_url": track.cover_url or COVER_URL,
            "role": _role_for(track),
            "audio_url": rendered.bridge.audio_url,
            "segment": segment.model_dump(mode="json"),
            "stage": "bridge",
            # The bridge's *actually* rendered crossfade -- render_bridge
            # may have clamped this defensively past what `transition`
            # below requested (see BridgeRender.crossfade_ms's docstring).
            # This exact value is what the next track's own body must
            # resume from once the bridge finishes, or audio at the seam
            # gets replayed or skipped.
            "resume_offset_ms": rendered.crossfade_ms,
            "reserved_ms": next_reserved_ms,
            "tail_audio_url": (
                rendered.next_reserved_tail.audio_url
                if rendered.next_reserved_tail
                else None
            ),
            "next_body_audio_url": rendered.next_body.audio_url,
        }
        renderer_is_pass_through = rendered.bridge.is_pass_through
        renderer_resolved_audio_url = rendered.bridge.audio_url
        renderer_fallback_reason = rendered.bridge.fallback_reason
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
        None
        if candidate_pool_reused
        else getattr(served_by, "last_candidate_scores", {}).get(_track_key(track))
    )
    cache_hit = (
        None if candidate_pool_reused else getattr(served_by, "last_cache_hit", None)
    )
    # "primary"/"fallback" alone (via fell_back) can't tell a weak-but-real
    # primary match (orchestrator.retrieve_candidates_with_fallback's tier 3)
    # apart from the last-resort "any row" tier (tier 4) -- both report
    # fell_back=False *or* True inconsistently depending on which of
    # {retriever, fallback_retriever, LAST_RESORT_CATALOG_RETRIEVER} actually
    # served, since the last-resort marker is a distinct object from
    # `retriever` specifically so fell_back reads True for it (see
    # catalog_retriever.LAST_RESORT_CATALOG_RETRIEVER's docstring). This is
    # the one three-way distinction (primary/fallback/last_resort) that
    # existing pipeline_trace fields don't already answer on their own --
    # added for §12's own "did the flip actually work" measurement, not a
    # new observability system.
    retriever_tier = (
        "last_resort"
        if served_by is LAST_RESORT_CATALOG_RETRIEVER
        else "fallback"
        if served_by is not retriever
        else "primary"
    )
    pipeline_trace = {
        "candidate_retriever": {
            "implementation": type(served_by).__name__,
            "name": served_by.name,
            "fell_back": served_by is not retriever,
            "tier": retriever_tier,
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
            "key_category": transition.key_category,
            "phrase_aligned": transition.phrase_aligned,
            "capped_by_reserved_window": transition.capped_by_reserved_window,
        },
        "audio_renderer": {
            "implementation": type(renderer).__name__,
            "is_pass_through": renderer_is_pass_through,
            "stage": now_playing["stage"],
            # The URL actually handed to the player, and -- when
            # is_pass_through is True -- why: surfaced so a "won't play"
            # report is diagnosable straight from the debug panel (was it
            # our own /media/renders/... file, or a raw external stream URL
            # that never got rendered at all, and if the latter, did the
            # download or the decode fail).
            "resolved_audio_url": renderer_resolved_audio_url,
            "fallback_reason": renderer_fallback_reason,
            # Candidates tried and discarded before landing on `track`
            # (empty when the first candidate rendered fine) -- see
            # AUDIO_RENDER_RETRY_LIMIT.
            "skipped_tracks": skipped_tracks,
        },
        # §8 observability, measurement only -- see this function's own
        # docstring for what each field covers.
        "_timing": {
            "retrieval_ms": retrieval_ms,
            **stage_timings,
            "total_ms": round((time.perf_counter() - resolve_started) * 1000, 2),
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
        mode=session.mode,
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
    prompt: str,
    db: Session,
    user_id: int | None,
    vibe: VibeUnderstander,
    mode: AutoMixMode | None = None,
) -> tuple[PromptIntent, PromptIntent]:
    """Returns (the intent this resolution actually uses -- possibly
    preference-biased, see _apply_preference -- and the raw intent
    vibe.understand() parsed from `prompt` before any bias). Callers that
    need to know what the user *actually* asked for this time (prompt_shortcuts'
    signature clustering) want the raw one; _resolve_and_render wants the
    first."""

    intent = apply_auto_mix_mode(vibe.understand(prompt), mode)
    is_neutral = (
        intent.energy == "medium" and intent.vocals == "neutral" and not intent.artist
    )
    # A named mode is an explicit instruction and must not be silently
    # rewritten by learned preferences. The free-prompt path retains the
    # existing preference behavior unchanged.
    if mode is None and is_neutral and user_id is not None:
        preferences = (
            db.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.score > 0)
            .order_by(UserPreference.score.desc(), UserPreference.count.desc())
            .all()
        )
        for preference in preferences:
            biased = _apply_preference(intent, preference.feedback)
            if biased is not None:
                return biased, intent
    return intent, intent


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
    mode: AutoMixMode | None = None,
) -> SessionRead:
    started = time.perf_counter()
    intent, raw_intent = _initial_intent(prompt, db, user_id, vibe, mode)
    # Generated up front (not left to the DJSession constructor below) so
    # _resolve_and_render can key session_candidate_pool by this session's
    # real, final id from its very first resolution -- a brand-new id has
    # never been cached, so this always falls through to a real retrieval
    # and populates the pool for the first advance() to reuse.
    session_id = f"session_{uuid4().hex}"
    track, _, now_playing, reasoning, pipeline_trace, served_by = _resolve_and_render(
        db,
        intent,
        retriever,
        fallback_retriever,
        selector,
        planner,
        renderer,
        session_id=session_id,
        previous_segment=None,
        prefers_smoother=False,
        viewer_id=user_id,
    )
    pipeline_trace["vibe_understander"] = {
        "implementation": type(vibe).__name__,
        "invoked": True,
        "auto_mix_mode": mode.value if mode else None,
        "intent": intent.model_dump(mode="json"),
        # Current == original at creation time, by definition.
        "original_intent": intent.model_dump(mode="json"),
    }

    session = DJSession(
        id=session_id,
        user_id=user_id,
        prompt=prompt,
        mode=mode.value if mode else None,
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
    if user_id is not None:
        # Keyed by the raw (un-biased) intent -- a signature must reflect
        # what this prompt actually asked for, not whatever an unrelated
        # past preference happened to nudge energy/vocals toward.
        prompt_shortcuts.record_prompt(db, user_id, prompt, raw_intent)
    db.commit()
    db.refresh(session)
    notify_pipeline_debug_change()
    publish_session_updated(session_id)
    _log_stage_latency("create_session", session_id, started, pipeline_trace)
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
    started = time.perf_counter()
    resolved_pipeline_trace: dict | None = None
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
        previous_segment = SelectedSegment.model_validate(
            session.now_playing_json["segment"]
        )
        recent_artists = frozenset(session.played_artists_json or [])
        try:
            track, _, now_playing, reasoning, pipeline_trace, served_by = (
                _resolve_and_render(
                    db,
                    mutated,
                    retriever,
                    fallback_retriever,
                    selector,
                    planner,
                    renderer,
                    session_id=session.id,
                    previous_segment=previous_segment,
                    prefers_smoother=prefers_smoother,
                    recent_artists=recent_artists,
                    viewer_id=session.user_id,
                )
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
            # PHASE_C_PREFETCH_DESIGN.md section 3.4: any prepared next item
            # was resolved against the now_playing/segment context this just
            # replaced, so it's stale regardless of *why* this resolution
            # ran. Unconditional on purpose: gating this on "mutated is not
            # current_intent" alone used to miss the "smoother" branch, which
            # leaves the intent (and so advance_session's fingerprint check)
            # unchanged while still replacing now_playing -- that check would
            # NOT have caught a stale prepared item in that case, only
            # explicit clearing here does.
            session.prepared_next_json = None
            _promote(
                session,
                now_playing=now_playing,
                reasoning=reasoning,
                pipeline_trace=pipeline_trace,
                retriever_name=served_by.name,
                vibe_label=now_playing["segment"]["track"]["vibe_label"],
                track_key=_track_key(track),
                artist=track.artist,
            )
            resolved_again = True
            resolved_pipeline_trace = pipeline_trace
        except NoMatchingCandidate:
            # Nothing matched the mutated intent closely enough; keep the
            # session on its current track rather than erroring out a live
            # session over one bad feedback mutation.
            pass
        except Exception:
            # Anything else genuinely unexpected (a bug, a transient DB
            # error, ...) must not surface as a hard failure either --
            # "Zero interruptions" means a session keeps playing through an
            # unanticipated pipeline error the same way it already does
            # through "nothing matched," not just the error conditions this
            # code happened to anticipate. Logged so the underlying issue
            # stays visible/fixable; never user-facing.
            logger.exception(
                "apply_feedback: unexpected error resolving session %s", session.id
            )

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
        publish_session_updated(session.id)
    _log_stage_latency("apply_feedback", session.id, started, resolved_pipeline_trace)
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
    """Continues a still-playing session onto the next segment of live
    audio matching its current (unmutated) intent once the current one
    finishes -- the continuous, no-input-required loop this pipeline was
    built around. Called automatically by the frontend on media-ended, not
    by user action, so it never mutates intent the way feedback does; it
    only rotates through the same candidate pool feedback would use,
    skipping whatever the session already played recently so it doesn't
    immediately repeat.

    Explicit coaching feedback (apply_feedback) still wins if the two race:
    both are ordinary commits to the same DJSession row, so whichever
    request's commit lands last is what persists -- no special locking
    needed, same as any other concurrent write to one row.

    Every selected segment reserves a fixed window at its own tail the
    moment it's chosen (see RESERVED_TRANSITION_MS/_reserved_ms_for) --
    session.now_playing_json["stage"] tracks which of three pieces is
    currently playing, and this function's job is to figure out which
    stage comes next, dispatching on it:

    - "bridge" -- the reserved tail already blended into a resolved next
      track's head is what's currently playing. It ends into that next
      track's own pre-rendered body, already staged in this same
      now_playing_json (next_body_audio_url/resume_offset_ms/reserved_ms/
      tail_audio_url) by the earlier body->bridge promotion below -- pure
      bookkeeping, no retrieval/render, no play-count change (a bridge
      already contains that track's audio, so play history was committed
      when the bridge itself started, not now).
    - "body" -- the current track's own (non-reserved) audio is playing.
      PHASE_C_PREFETCH_DESIGN.md section 3.3: if prepare_next() already
      parked a still-valid *bridge* for this exact intent, that's promoted
      directly (no retrieve/select/plan/render) -- re-validated against the
      session's *current* intent fingerprint right here, not trusted just
      because it exists, since feedback may have mutated the intent after
      it was prepared but before this call landed. Fingerprint + TTL alone
      aren't enough, though: prepare_next() can still be resolving (its
      render alone can take 25s+, well past the ~10s of track remaining
      that triggers it) when this session's current track ends and this
      call runs its own resolution first, independently landing on the same
      track (selection is fully deterministic, and both runs share the same
      intent/exclude set) -- prepare_next() then finishes and writes that
      same track as "prepared," which this fast path would otherwise replay
      immediately on the *next* advance. So the prepared item is also
      rejected outright if its track_key is already in played_track_keys_json,
      falling through instead. Absent a ready bridge, the segment's own
      already-rendered reserved tail (this stage's `reserved_ms`/
      `tail_audio_url`) plays next verbatim, unblended ("reserved_plain") --
      never cut short, and never a fresh resolution while there's still
      reserved audio left to honestly play. Only when nothing was reserved
      at all (a very short segment; see _reserved_ms_for) does this fall
      straight through to a fresh resolution instead.
    - "reserved_plain", or no "stage" key at all (a session row from before
      this mechanism existed) -- nothing further is already staged; falls
      through to a genuinely fresh resolution, exactly like this function's
      only behavior before live crossfades existed."""

    started = time.perf_counter()
    intent = PromptIntent.model_validate(session.intent_json)
    now_playing = session.now_playing_json
    stage = now_playing.get("stage")

    if stage == "bridge":
        promoted = {
            key: now_playing[key]
            for key in ("title", "artist", "album", "cover_url", "role", "segment")
        }
        promoted.update(
            audio_url=now_playing["next_body_audio_url"],
            stage="body",
            resume_offset_ms=now_playing["resume_offset_ms"],
            reserved_ms=now_playing["reserved_ms"],
            tail_audio_url=now_playing["tail_audio_url"],
        )
        _promote(
            session,
            now_playing=promoted,
            reasoning=session.reasoning_json,
            pipeline_trace=session.pipeline_trace_json,
            retriever_name=session.retriever_name,
            vibe_label=session.vibe_label,
        )
        db.commit()
        db.refresh(session)
        notify_pipeline_debug_change()
        publish_session_updated(session.id)
        _log_stage_latency("advance_session", session.id, started, None)
        return serialize_session(session)

    if stage == "body":
        fingerprint = session_candidate_pool.fingerprint_for(intent)
        prepared = session.prepared_next_json
        played_track_keys = session.played_track_keys_json or []
        if (
            _prepared_is_valid(prepared, fingerprint)
            and prepared["track_key"] not in played_track_keys
        ):
            pipeline_trace = prepared["pipeline_trace"]
            pipeline_trace["vibe_understander"] = {
                "implementation": type(get_vibe_understander()).__name__,
                "invoked": False,
                "intent": intent.model_dump(mode="json"),
                "original_intent": _effective_original_intent(session),
            }
            _promote(
                session,
                now_playing=prepared["now_playing"],
                reasoning=prepared["reasoning"],
                pipeline_trace=pipeline_trace,
                retriever_name=pipeline_trace["candidate_retriever"]["name"],
                vibe_label=prepared["now_playing"]["segment"]["track"]["vibe_label"],
                track_key=prepared["track_key"],
                artist=prepared["artist"],
            )
            session.prepared_next_json = None
            db.commit()
            db.refresh(session)
            notify_pipeline_debug_change()
            publish_session_updated(session.id)
            _log_stage_latency("advance_session", session.id, started, None)
            return serialize_session(session)

        reserved_ms = now_playing.get("reserved_ms", 0)
        tail_audio_url = now_playing.get("tail_audio_url")
        if reserved_ms > 0 and tail_audio_url:
            # No bridge ready yet -- the reserved window still plays in
            # full, verbatim, rather than ever being skipped or cut short;
            # a fresh resolution only happens once *this* ends too.
            promoted = {
                key: now_playing[key]
                for key in ("title", "artist", "album", "cover_url", "role", "segment")
            }
            promoted.update(
                audio_url=tail_audio_url,
                stage="reserved_plain",
                resume_offset_ms=0,
                reserved_ms=0,
                tail_audio_url=None,
            )
            _promote(
                session,
                now_playing=promoted,
                reasoning=session.reasoning_json,
                pipeline_trace=session.pipeline_trace_json,
                retriever_name=session.retriever_name,
                vibe_label=session.vibe_label,
            )
            db.commit()
            db.refresh(session)
            notify_pipeline_debug_change()
            publish_session_updated(session.id)
            _log_stage_latency("advance_session", session.id, started, None)
            return serialize_session(session)
        # reserved_ms == 0 (nothing was reserved for this segment -- see
        # _reserved_ms_for) -- falls through to a fresh resolution below,
        # same as "reserved_plain" already finishing.

    # stage in (None, "reserved_plain"), or "body" with nothing reserved --
    # a genuinely fresh resolution, exactly like this function's only
    # behavior before live crossfades existed.
    previous_segment = SelectedSegment.model_validate(now_playing["segment"])
    exclude = frozenset(session.played_track_keys_json or [])
    recent_artists = frozenset(session.played_artists_json or [])
    try:
        track, _, fresh_now_playing, reasoning, pipeline_trace, served_by = (
            _resolve_and_render(
                db,
                intent,
                retriever,
                fallback_retriever,
                selector,
                planner,
                renderer,
                session_id=session.id,
                previous_segment=previous_segment,
                prefers_smoother=False,
                exclude_track_keys=exclude,
                recent_artists=recent_artists,
                viewer_id=session.user_id,
            )
        )
    except NoMatchingCandidate:
        # Nothing to advance to (e.g. Audius briefly unreachable); leave the
        # session on its current track rather than ending it outright.
        _log_stage_latency("advance_session", session.id, started, None)
        return serialize_session(session)
    except Exception:
        # Same "never a hard stop" guarantee for anything genuinely
        # unexpected, not just the "nothing matched" case this code already
        # anticipated -- see apply_feedback's identical guard. Logged so
        # the underlying bug stays visible; the session just keeps playing
        # its current track instead of surfacing a 500 that ends playback.
        logger.exception(
            "advance_session: unexpected error resolving session %s", session.id
        )
        _log_stage_latency("advance_session", session.id, started, None)
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
    _promote(
        session,
        now_playing=fresh_now_playing,
        reasoning=reasoning,
        pipeline_trace=pipeline_trace,
        retriever_name=served_by.name,
        vibe_label=fresh_now_playing["segment"]["track"]["vibe_label"],
        track_key=_track_key(track),
        artist=track.artist,
    )

    db.commit()
    db.refresh(session)
    notify_pipeline_debug_change()
    publish_session_updated(session.id)
    _log_stage_latency("advance_session", session.id, started, pipeline_trace)
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
    """PHASE_C_PREFETCH_DESIGN.md section 3.2, extended for live in-session
    crossfades: while the session's current segment is in its "body" stage
    (see advance_session's docstring for the full stage state machine),
    tries to resolve and render a *bridge* out of that body's own
    already-rendered reserved tail ahead of the ~10s of track remaining
    that triggers this call, and parks the result in
    session.prepared_next_json instead of the live now_playing_json/
    reasoning_json/pipeline_trace fields -- nothing this session currently
    reports as playing is touched. A no-op if the session isn't
    `"playing"`, if its current stage isn't "body" (a bridge or reserved
    tail is already staged or playing -- nothing further to look ahead to
    until a fresh resolution happens), if nothing was reserved for the
    current segment at all (see _reserved_ms_for), or if a still-valid
    (unexpired, current-fingerprint) prepared item already exists.

    Guarded by a per-session Lock so two near-simultaneous calls for the
    same session don't both pay for a full retrieval/render -- see the
    module-level _prepare_locks comment for why this is a latency nicety,
    not a correctness requirement (section 3.5).

    A different race matters more: stop_session(), apply_feedback() (the
    branch that clears prepared_next_json on intent mutation), or
    advance_session() itself (which can promote the current body's own
    reserved tail straight into "reserved_plain" while this is still
    resolving) can all commit *while* this function's own retrieval/render
    work is still running. Without a re-check, this function's eventual
    write would land afterward and silently resurrect a prepared bridge
    built from a tail the session has already moved past -- so right
    before writing, the session's current state is re-fetched and
    re-validated against the fingerprint this resolution actually ran
    against *and* the exact tail_audio_url it bridged from (fingerprint
    alone isn't enough: the intent can stay unchanged across an unrelated
    stage transition), and the result is discarded if any of it no longer
    matches: not written to the DB, and every file this call rendered (the
    bridge, the next track's own body, and its own new reserved tail) is
    deleted too (_delete_rendered_file) rather than left as a permanent
    orphan on disk. This is a normal, expected outcome of the race, not an
    error.

    §8 observability (measurement only): logs exactly once per call,
    regardless of which return point above actually fires, via the outer
    try/finally below -- see _PREPARE_NEXT_MIN_FRONTEND_DEADLINE_MS/
    _PREPARE_NEXT_CLIENT_TIMEOUT_MS's own comment for what this call's
    duration is compared against, and why those two numbers (not an exact
    deadline) are the honest comparison a backend-only measurement can
    make."""

    started = time.perf_counter()
    resolved_pipeline_trace: dict | None = None
    try:
        if session.status != "playing":
            return

        lock = _prepare_lock_for(session.id)
        if not lock.acquire(blocking=False):
            # Another prepare_next() call for this session is already doing
            # the real work; its result (or lack of one) is what matters,
            # not a second redundant attempt.
            return
        try:
            if session.now_playing_json.get("stage") != "body":
                # A bridge or a reserved tail is already staged or playing --
                # advance_session already knows what comes next without this.
                return

            intent = PromptIntent.model_validate(session.intent_json)
            fingerprint = session_candidate_pool.fingerprint_for(intent)
            if _prepared_is_valid(session.prepared_next_json, fingerprint):
                return

            origin_now_playing = session.now_playing_json
            origin_tail_audio_url = origin_now_playing.get("tail_audio_url")
            origin_reserved_ms = origin_now_playing.get("reserved_ms", 0)
            if not origin_tail_audio_url or origin_reserved_ms <= 0:
                # Nothing was reserved for the current segment (a very short
                # one -- see _reserved_ms_for) -- advance_session falls
                # straight through to a fresh resolution once it ends; there's
                # nothing to bridge from ahead of time.
                return
            bridge_from = StagedRender(
                audio_url=origin_tail_audio_url, duration_ms=origin_reserved_ms
            )

            previous_segment = SelectedSegment.model_validate(
                origin_now_playing["segment"]
            )
            exclude = frozenset(session.played_track_keys_json or [])
            recent_artists = frozenset(session.played_artists_json or [])
            try:
                track, _, now_playing, reasoning, pipeline_trace, _served_by = (
                    _resolve_and_render(
                        db,
                        intent,
                        retriever,
                        fallback_retriever,
                        selector,
                        planner,
                        renderer,
                        session_id=session.id,
                        previous_segment=previous_segment,
                        prefers_smoother=False,
                        exclude_track_keys=exclude,
                        recent_artists=recent_artists,
                        viewer_id=session.user_id,
                        bridge_from=bridge_from,
                    )
                )
            except NoMatchingCandidate:
                # Nothing to bridge into ahead of time; advance_session falls
                # back to its own real resolution (the reserved tail playing
                # out plain, then a fresh one) when it's actually needed, same
                # as it always has.
                return
            except Exception:
                # This is already a best-effort prefetch (see this function's
                # docstring); an unanticipated error here must be even less
                # visible than a NoMatchingCandidate, not more -- log it and
                # let advance_session() do its own (now equally resilient)
                # real resolution when it's actually needed.
                logger.exception(
                    "prepare_next: unexpected error resolving session %s", session.id
                )
                return

            resolved_pipeline_trace = pipeline_trace

            # Re-fetch and re-validate right before writing: stop_session(),
            # apply_feedback(), or advance_session() itself may have committed
            # while the retrieval/render work above was in flight. db.refresh()
            # picks up whatever is actually committed now, not whatever this
            # function saw when it started -- a plain re-check of the in-memory
            # `session` object wouldn't catch a change made through a different
            # Session/request.
            db.refresh(session)
            current_intent = PromptIntent.model_validate(session.intent_json)
            current_fingerprint = session_candidate_pool.fingerprint_for(current_intent)
            current_now_playing = session.now_playing_json
            if (
                session.status != "playing"
                or current_fingerprint != fingerprint
                or current_now_playing.get("stage") != "body"
                or current_now_playing.get("tail_audio_url") != origin_tail_audio_url
            ):
                # The DB record is correctly never written on this path, but
                # the audio files _resolve_and_render already rendered to disk
                # above are now unused and would otherwise sit there as
                # permanent orphans (see _delete_rendered_file) until the next
                # _export() call's TTL sweep happens to catch them.
                for stale_url in (
                    now_playing.get("audio_url"),
                    now_playing.get("next_body_audio_url"),
                    now_playing.get("tail_audio_url"),
                ):
                    if stale_url:
                        _delete_rendered_file(stale_url)
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
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        entry = {
            "event": "prepare_next_latency",
            "session_id": session.id,
            "total_ms": duration_ms,
            "resolved": resolved_pipeline_trace is not None,
        }
        if resolved_pipeline_trace is not None:
            entry["resolution"] = resolved_pipeline_trace.get("_timing", {})
            # Conservative proxies, not exact deadlines -- see this
            # function's own docstring and the two constants' comments.
            entry["beat_min_frontend_deadline"] = (
                duration_ms <= _PREPARE_NEXT_MIN_FRONTEND_DEADLINE_MS
            )
            entry["beat_client_timeout"] = (
                duration_ms <= _PREPARE_NEXT_CLIENT_TIMEOUT_MS
            )
        logger.info(json.dumps(entry))
        record_event(entry)


def stop_session(db: Session, session: DJSession) -> dict:
    session.status = "stopped"
    session.prepared_next_json = None
    db.commit()
    return {
        "session_id": session.id,
        "status": "stopped",
        "message": "AI DJ session stopped.",
    }
