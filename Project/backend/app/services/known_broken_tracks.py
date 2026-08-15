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

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.session import KnownBrokenTrack
from app.schemas import Track

# How long a KnownBrokenTrack row is trusted before a session is willing to
# try that track again. Long enough to actually save repeated failed
# download attempts across a burst of sessions hitting the same broken
# track (the observed case: 5+ sessions in a row); short enough that a
# track which becomes available again isn't skipped indefinitely.
KNOWN_BROKEN_TRACK_TTL_SECONDS = 86400.0


def _track_key(track: Track) -> str:
    return f"{track.source}:{track.source_track_id}"


def is_known_broken(db: Session, track_key: str) -> bool:
    """False for no entry, or an entry older than KNOWN_BROKEN_TRACK_TTL_SECONDS
    -- callers never need to distinguish why, same "miss is always safe"
    contract as session_candidate_pool.get(). An expired row is deleted here
    (piggybacked on this lookup) rather than on a timer -- this codebase has
    no background task runner, so cleanup always rides along with a real
    call, same idiom as audio_renderer._sweep_stale_renders()."""

    row = db.get(KnownBrokenTrack, track_key)
    if row is None:
        return False
    if utc_now() - row.last_seen_at >= timedelta(seconds=KNOWN_BROKEN_TRACK_TTL_SECONDS):
        db.delete(row)
        return False
    return True


def mark_broken(db: Session, track: Track, fallback_reason: str) -> None:
    """Upserts a KnownBrokenTrack row for `track`. Does not commit -- the
    caller controls the transaction boundary, same as every other mutation
    in session_manager.py's resolution flow."""

    track_key = _track_key(track)
    row = db.get(KnownBrokenTrack, track_key)
    if row is None:
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
        # Flushed (not committed -- the caller still owns that) so a second
        # mark_broken call for the same track_key within the same
        # transaction sees this row via db.get() above instead of also
        # taking the insert branch and colliding on the primary key.
        db.flush()
        return
    row.failure_count += 1
    row.fallback_reason = fallback_reason
    row.last_seen_at = utc_now()
