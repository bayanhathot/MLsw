"""In-memory, per-process cache of a session's ranked candidate pool.

advance_session() re-runs QueryPlanner -> MultiQueryAudiusRetriever -> RRF
-> ranking on every call, even when nothing about the intent has changed
since the session's last resolution. This cache lets an unchanged intent
reuse the already-ranked pool instead of repeating that whole pipeline.
Plain Lock-guarded module state, the same idiom prompt_parser.py/
audius_service.py already use for their own process-local caches -- not a
new dependency, and not shared across worker processes (each keeps its own
cache, which is fine: this is a pure latency optimization, never a
correctness dependency -- a miss always falls through to a real retrieval,
same as every other cache in this codebase).
"""

import os
import time
from threading import Lock

from app.schemas import PromptIntent, Track

# Longer than AUDIUS_SEARCH_CACHE_TTL_SECONDS (audius_service.py): this
# represents a whole session's already-ranked candidate set, not one raw
# query result, so it's reasonable to keep it around for longer.
SESSION_CANDIDATE_POOL_TTL_SECONDS = float(
    os.getenv("SESSION_CANDIDATE_POOL_TTL_SECONDS", "600")
)
# A session that's created and then abandoned (never advanced or given
# feedback again) would otherwise leave a permanent entry here -- get() only
# prunes an entry when it's actually looked up again past its TTL, which
# never happens for an abandoned session. Same bound-and-evict pattern as
# audius_service.py's AUDIUS_SEARCH_CACHE_MAX_ENTRIES.
SESSION_CANDIDATE_POOL_MAX_ENTRIES = int(
    os.getenv("SESSION_CANDIDATE_POOL_MAX_ENTRIES", "500")
)

# The subset of PromptIntent that actually affects query_planner.build_queries
# and audius_retriever._score_candidates today. vocals and search_query are
# deliberately excluded -- neither build_queries nor _score_candidates reads
# them, so a vocals-only or search_query-only difference would still rank
# the exact same pool the exact same way; caching by this narrower key lets
# those cases still reuse it instead of being treated as a miss.
RetrievalFingerprint = tuple[str | None, str, tuple[str, ...], str, str]

_lock = Lock()
# session_id -> (fingerprint, tracks, cached_at). Regular dicts preserve
# insertion order, which the oldest-first eviction in put() relies on -- not
# a full LRU, just enough to keep this bounded without extra bookkeeping.
_pools: dict[str, tuple[RetrievalFingerprint, list[Track], float]] = {}


def fingerprint_for(intent: PromptIntent) -> RetrievalFingerprint:
    return (
        intent.artist,
        intent.artist_mode,
        tuple(sorted(intent.genres)),
        intent.mood,
        intent.energy,
    )


def get(session_id: str, current_fingerprint: RetrievalFingerprint) -> list[Track] | None:
    """None on a missing entry, a fingerprint mismatch (the intent changed
    since this pool was cached), or an expired entry -- callers never need
    to distinguish why, they just fall through to a real retrieval either
    way, the same "miss is always safe" contract every cache here follows."""

    with _lock:
        entry = _pools.get(session_id)
        if entry is None:
            return None
        fingerprint, tracks, cached_at = entry
        if fingerprint != current_fingerprint:
            return None
        if time.monotonic() - cached_at >= SESSION_CANDIDATE_POOL_TTL_SECONDS:
            # Expired -- drop it so a stale entry never lingers past its TTL.
            del _pools[session_id]
            return None
        return tracks


def put(session_id: str, fingerprint: RetrievalFingerprint, tracks: list[Track]) -> None:
    with _lock:
        if session_id not in _pools and len(_pools) >= SESSION_CANDIDATE_POOL_MAX_ENTRIES:
            oldest_session_id = next(iter(_pools))
            del _pools[oldest_session_id]
        _pools[session_id] = (fingerprint, tracks, time.monotonic())
