"""Prompt 3 (+ Prompt 4): the persistent, provider-keyed Audius analysis
cache -- batched lookup/enrichment, atomic first-encounter dispatch, and
fingerprint-triggered re-analysis, wired into the one real choke point
every session resolution already shares (session_manager._resolve_and_render,
called by create_session/apply_feedback/advance_session/prepare_next
alike -- verified by reading the code, not assumed; see Prompt 3 step 4).

Gated end-to-end behind AUDIUS_ANALYSIS_CACHE_ENABLED, default False and
tied to the Prompt 0 compliance gate (Project/SECURITY.md's "Third-party
compliance gates" section): with the flag off, enrich_and_dispatch() is a
first-line no-op, so no external_tracks row is ever created and no
temporary Audius audio is ever fetched for analysis in production until
that gate is cleared. Do not flip the default without updating that
SECURITY.md section first.

Concurrency: every dispatch (Case B's atomic insert, and any re-enqueue
below) shares upload_queue.py's existing bounded worker pool -- Audius
documents no explicit rate limit this codebase is aware of (checked:
audius_service.py has no rate-limiting logic), so that shared pool's
existing `workers` concurrency is the only cap in effect, same as every
other analysis job this queue already runs.

Retry/staleness policy note: unlike catalog_tracks (which never
auto-retries a *failed* row -- see ExternalTrack.analysis_attempt_count's
own docstring), external_tracks rows ARE capped-retried here
(EXTERNAL_ANALYSIS_MAX_ATTEMPTS, audio_analysis.py), since this cache's
whole point is to eventually converge a first-seen track to a completed
state without a human re-triggering an upload. Three distinct kinds of
"needs another analysis attempt" are handled differently on purpose:
  - `is_stale` (a fingerprint mismatch, Prompt 4): the audio itself may
    have changed underneath the old analysis, so it's flipped to
    "pending" immediately -- SegmentSelector already stops trusting it
    the moment is_stale is True, so flipping the status costs no trust
    and gets a real dedup benefit (a concurrent encounter sees "pending"
    and skips, exactly like Case C).
  - "failed": already fully untrusted (SegmentSelector never accepted a
    non-"completed" row), so the same "flip to pending, dedup for free"
    reasoning applies.
  - "completed" but `analysis_version` behind ANALYSIS_VERSION: the
    proposal is explicit that a version-stale row must stay playable
    with its existing (still-correct, just possibly improvable) analysis
    while a fresh pass runs in the background -- so analysis_status is
    deliberately left untouched here. The tradeoff: without a status flip
    to key dedup off, a short burst of concurrent encounters for the same
    version-stale row can each independently decide to re-dispatch before
    the first one finishes and bumps analysis_version. Accepted as
    bounded, not silent: analyze_external_track() still increments
    analysis_attempt_count on every real run, so
    EXTERNAL_ANALYSIS_MAX_ATTEMPTS caps the worst case at a handful of
    duplicate jobs total for one row, never unboundedly many.
"""

import logging
import os

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.external_track import ExternalTrack
from app.schemas import Track
from app.services import upload_queue
from app.services.admin_debug_events import publish_external_track_updated
from app.services.audio_analysis import ANALYSIS_VERSION, EXTERNAL_ANALYSIS_MAX_ATTEMPTS

logger = logging.getLogger(__name__)

# See this module's own docstring for what flipping this on actually does,
# and why it defaults off.
AUDIUS_ANALYSIS_CACHE_ENABLED = os.getenv("AUDIUS_ANALYSIS_CACHE_ENABLED", "false").lower() in (
    "1", "true", "yes",
)


def _dispatch(external_track_id: int) -> None:
    publish_external_track_updated(external_track_id)
    try:
        upload_queue.upload_queue.submit_external_analysis(external_track_id)
    except Exception:
        # A full/unavailable queue must never break retrieval -- the row is
        # left exactly as it was (still "pending"/"failed"/is_stale), so a
        # later encounter's own enrich_and_dispatch call gets another
        # chance to enqueue it. Mirrors upload_queue.submit_analysis's own
        # call sites, which already tolerate a Full queue the same way.
        logger.warning(
            "external_track_cache: failed to dispatch analysis for external_track_id=%s",
            external_track_id, exc_info=True,
        )


def _create_or_get_existing(db: Session, track: Track) -> tuple[ExternalTrack | None, bool]:
    """Atomic first-encounter insert, mirroring known_broken_tracks.mark_broken's
    exact begin_nested()/IntegrityError race pattern (see that module for
    the full rationale) rather than a dialect-specific ON CONFLICT clause --
    this codebase already has one load-bearing precedent for this exact
    problem shape, so reusing its idiom keeps the two easy to compare
    later, and it works identically against SQLite (tests) and Postgres
    (production) with no dialect branching.

    Returns (row, True) if this call's own insert won the race (the
    caller should dispatch analysis); (row, False) if a concurrent
    request already won it (the caller must not dispatch a duplicate --
    Prompt 3's own dedup requirement)."""

    try:
        with db.begin_nested():
            row = ExternalTrack(
                source=track.source,
                external_id=track.source_track_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                genre=track.genre,
                duration_sec=track.duration_seconds,
                provider_metadata_json={"tags": track.tags, "vibe": track.vibe} if (track.tags or track.vibe) else None,
                analysis_status="pending",
            )
            db.add(row)
            db.flush()
    except IntegrityError:
        row = (
            db.query(ExternalTrack)
            .filter(ExternalTrack.source == track.source, ExternalTrack.external_id == track.source_track_id)
            .first()
        )
        if row is None:
            # Shouldn't happen (the conflict implies a row exists) -- never
            # leave this unresolved; the caller just skips enrichment for
            # this one candidate this call, a future encounter tries again.
            return None, False
        return row, False
    else:
        db.commit()
        return row, True


def enrich_and_dispatch(db: Session, candidates: list[Track]) -> None:
    """Batched (Prompt 3 step 1: ONE query for the whole candidate set,
    never a per-candidate query in a loop) cache lookup for every Audius
    candidate in `candidates`, mutating each matching Track's
    `external_track_id` in place. New/stale/failed rows are dispatched for
    (re-)analysis per this module's own docstring. A no-op, with zero
    query cost, when AUDIUS_ANALYSIS_CACHE_ENABLED is False or `candidates`
    contains no Audius tracks."""

    if not AUDIUS_ANALYSIS_CACHE_ENABLED:
        return

    by_external_id: dict[str, list[Track]] = {}
    for track in candidates:
        if track.source != "audius":
            continue
        by_external_id.setdefault(track.source_track_id, []).append(track)
    if not by_external_id:
        return

    existing_rows = {
        row.external_id: row
        for row in db.query(ExternalTrack)
        .filter(
            ExternalTrack.source == "audius",
            ExternalTrack.external_id.in_(by_external_id.keys()),
        )
        .all()
    }

    now = utc_now()
    for external_id, tracks in by_external_id.items():
        row = existing_rows.get(external_id)
        needs_dispatch = False

        if row is None:
            row, won = _create_or_get_existing(db, tracks[0])
            needs_dispatch = won
        else:
            row.last_seen_at = now
            if row.analysis_status == "pending":
                pass  # Case C: already queued, don't duplicate
            elif row.analysis_status == "completed" and row.is_stale:
                if row.analysis_attempt_count < EXTERNAL_ANALYSIS_MAX_ATTEMPTS:
                    row.analysis_status = "pending"
                    needs_dispatch = True
            elif row.analysis_status == "completed" and row.analysis_version != ANALYSIS_VERSION:
                if row.analysis_attempt_count < EXTERNAL_ANALYSIS_MAX_ATTEMPTS:
                    needs_dispatch = True  # status left as "completed" -- see module docstring
            elif row.analysis_status == "failed":
                if row.analysis_attempt_count < EXTERNAL_ANALYSIS_MAX_ATTEMPTS:
                    row.analysis_status = "pending"
                    needs_dispatch = True
            # else: analysis_status == "completed", current version, not
            # stale -- Case A, nothing to do.
            db.commit()

        if row is not None:
            for track in tracks:
                track.external_track_id = row.id
        if needs_dispatch and row is not None:
            _dispatch(row.id)


def verify_fingerprint(db: Session, track: Track, audio_sha256: str | None) -> None:
    """Prompt 4: called once per resolved render with the SHA-256 of
    whatever complete remote bytes the render path actually fetched for
    `track` (see AudioRenderer.render_track_transition/render_bridge and
    StagedRender.audio_sha256's own docstring for exactly where that hash
    comes from -- always a byproduct of a fetch the render path needed
    anyway, never a separate network request purely for this check).

    A no-op whenever there's nothing to verify: `track.external_track_id`
    unset (never cached), or `audio_sha256` None (a local_path load, or
    the render failed before any bytes were fetched).

    On a match: no DB write at all -- the common, hot-path case stays
    completely free of write traffic (see this function's own test for
    why that's asserted, not just assumed).

    On a mismatch: is_stale flips True and re-analysis is dispatched
    (mirroring the "failed"/is_stale dispatch branch in
    enrich_and_dispatch, same attempt cap) -- audio_sha256 and every
    other analysis field are left exactly as they are; only a fresh,
    successful analyze_external_track() run ever overwrites them (see
    that function's own is_stale=False reset at the end)."""

    if track.external_track_id is None or audio_sha256 is None:
        return

    row = db.query(ExternalTrack).filter(ExternalTrack.id == track.external_track_id).first()
    if row is None or row.audio_sha256 is None:
        return
    if row.audio_sha256 == audio_sha256:
        return

    logger.warning(
        "external_track_cache: fingerprint mismatch for external_track_id=%s -- "
        "marking cached analysis stale.",
        row.id,
    )
    row.is_stale = True
    if row.analysis_attempt_count < EXTERNAL_ANALYSIS_MAX_ATTEMPTS:
        row.analysis_status = "pending"
        db.commit()
        _dispatch(row.id)  # also publishes external_track_updated
    else:
        db.commit()
        publish_external_track_updated(row.id)
