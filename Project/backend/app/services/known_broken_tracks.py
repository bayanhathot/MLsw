"""Cross-session memory of tracks whose audio recently failed to render.

_resolve_and_render (session_manager.py) already retries a fixed number of
ranked candidates within one resolution when a track's audio can't be
fetched/decoded (AUDIO_RENDER_RETRY_LIMIT), but that retry has no memory
across resolutions: a systemically broken source (e.g. Audius returning a
403 for one specific track) gets rediscovered -- and its real download
re-attempted, timeout and all -- by every new session that happens to rank
it highly. This module persists that discovery in known_broken_tracks so a
later session can skip straight past it instead of re-paying that cost.

Not a permanent blacklist: provider-side availability can change (a
takedown can be temporary, a track can be re-uploaded), so every entry has
a TTL after which a session is willing to try it again. Persisted in the DB
(not an in-memory cache like session_candidate_pool.py) because this
project's deploy cadence restarts the backend process often enough that an
in-memory-only registry would rarely accumulate useful history.
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.session import KnownBrokenTrack
from app.schemas import Track

# How long a KnownBrokenTrack row is trusted before a session is willing to
# try that track again, for a failure that looks likely to still be true
# tomorrow (see _is_likely_permanent) -- e.g. a 403/404, or a download that
# succeeded but decoded to something that isn't valid audio. Long enough to
# actually save repeated failed download attempts across a burst of
# sessions hitting the same broken track (the observed case: 5+ sessions in
# a row); short enough that a track which becomes available again isn't
# skipped indefinitely.
KNOWN_BROKEN_TRACK_TTL_SECONDS = 86400.0

# Everything else -- a 5xx, a connection reset, a timeout, an exceeded size
# cap -- more plausibly reflects the provider (or network) having a bad
# moment than the track itself being gone (confirmed live: a track that
# 503'd once was, minutes later, playable and well-liked on Audius's own
# site). Remembered only briefly, so a session tries again soon instead of
# writing a perfectly fine track off for a full day over one blip.
TRANSIENT_KNOWN_BROKEN_TTL_SECONDS = 300.0


def _track_key(track: Track) -> str:
    return f"{track.source}:{track.source_track_id}"


def _is_likely_permanent(fallback_reason: str) -> bool:
    """True for the failure modes worth remembering for the long
    KNOWN_BROKEN_TRACK_TTL_SECONDS window: a 4xx (403 Forbidden, 404 Not
    Found, ...) means the provider deliberately won't serve this track, and
    a decode failure means the bytes it did serve aren't valid audio --
    both are properties of the track, not the moment. Everything else
    defaults to the short TRANSIENT_KNOWN_BROKEN_TTL_SECONDS instead of
    trying to enumerate every possible transient httpx/network exception
    name; the cost of guessing wrong here is one extra download attempt
    per TTL window, never a track wrongly skipped forever."""

    return fallback_reason.startswith("download_failed_http_4") or fallback_reason.startswith(
        "decode_failed_"
    )


def is_known_broken(db: Session, track_key: str) -> bool:
    """False for no entry, or an entry past its TTL (see
    KNOWN_BROKEN_TRACK_TTL_SECONDS / TRANSIENT_KNOWN_BROKEN_TTL_SECONDS,
    chosen by the recorded failure's own likely permanence) -- callers never
    need to distinguish why, same "miss is always safe" contract as
    session_candidate_pool.get(). An expired row is deleted here
    (piggybacked on this lookup) rather than on a timer -- this codebase has
    no background task runner, so cleanup always rides along with a real
    call, same idiom as audio_renderer._sweep_stale_renders()."""

    row = db.get(KnownBrokenTrack, track_key)
    if row is None:
        return False
    ttl = (
        KNOWN_BROKEN_TRACK_TTL_SECONDS
        if _is_likely_permanent(row.fallback_reason)
        else TRANSIENT_KNOWN_BROKEN_TTL_SECONDS
    )
    if utc_now() - row.last_seen_at >= timedelta(seconds=ttl):
        db.delete(row)
        return False
    return True


def mark_broken(db: Session, track: Track, fallback_reason: str) -> None:
    """Upserts a KnownBrokenTrack row for `track`, committing it immediately
    -- unlike every other mutation in session_manager.py's resolution flow,
    this can't wait for the caller's own db.commit(): prepare_next() and
    advance_session() can run concurrently for the same session by design
    (PHASE_C_PREFETCH_DESIGN.md), so two separate requests/DB sessions can
    discover the same newly-broken track at nearly the same moment and both
    try to insert the same track_key. The insert runs inside a
    db.begin_nested() savepoint so a losing IntegrityError only rolls back
    this one row -- not any unrelated pending work the caller, or an
    earlier candidate in the same retry loop, already staged on this
    Session -- and the loser then just updates the winner's row instead."""

    track_key = _track_key(track)
    row = db.get(KnownBrokenTrack, track_key)
    if row is None:
        try:
            with db.begin_nested():
                db.add(
                    KnownBrokenTrack(
                        track_key=track_key,
                        source=track.source,
                        source_track_id=track.source_track_id,
                        title=track.title,
                        fallback_reason=fallback_reason,
                        failure_count=1,
                    )
                )
                db.flush()
        except IntegrityError:
            row = db.get(KnownBrokenTrack, track_key)
            if row is None:
                # A concurrent insert lost the race and yet no row is
                # visible -- shouldn't happen (the conflict implies one
                # exists), but never leave this uncommitted/unresolved.
                return
        else:
            db.commit()
            return
    row.failure_count += 1
    row.fallback_reason = fallback_reason
    row.last_seen_at = utc_now()
    db.commit()
