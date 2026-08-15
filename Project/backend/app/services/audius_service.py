"""Audius service for Cuemix.

This service is responsible for communicating with the external Audius API.

Why this file exists:
- The router should not directly contain external API logic.
- This file keeps Audius-specific code separated from FastAPI route code.
- The rest of the backend can call search_tracks() without knowing the raw
  Audius API format.

Behavior:
1. Receive a user prompt, for example: "chill electronic focus".
2. Send the prompt to Audius track search.
3. Receive raw Audius track data.
4. Extract only the fields Cuemix needs: track id, title, artist, duration,
   cover image, stream URL.
5. Return a clean list of track dictionaries.

This service only fetches candidate tracks -- it never creates catalog
records. AudiusCandidateRetriever (pipeline/audius_retriever.py) wraps it
behind the same CandidateRetriever interface as the local catalog. Mixes
primary-retrieve from here and fall back to the catalog when a search
returns nothing (mix_service._retrieve_with_fallback); sessions
primary-retrieve from the catalog and fall back to here the other direction
(orchestrator.retrieve_candidates_with_fallback, session_manager.py) --
see AI_DJ_PIPELINE.md for the full picture. Provider failures (HTTP errors,
timeouts, malformed payloads) are caught below and degrade to an empty
result list rather than raising, the same fail-open pattern as the optional
Ollama VibeUnderstander implementation.
"""

import logging
import os
import time
from threading import Lock
from urllib.parse import quote

import httpx

# Base URL for the Audius Discovery API. Overridable so a self-hosted or
# alternate discovery node can be swapped in without a code change, matching
# how OLLAMA_BASE_URL is configured.
AUDIUS_API_BASE = os.getenv("AUDIUS_API_BASE", "https://discoveryprovider.audius.co/v1").rstrip("/")
APP_NAME = "Cuemix"
logger = logging.getLogger(__name__)

# Short-TTL, bounded search cache in front of the real Audius call. A single
# MultiQueryAudiusRetriever resolution often repeats a query another recent
# resolution already made (the same genre/mood terms recur across prompts),
# so this is a pure latency optimization -- a miss, an expired entry, or any
# internal cache error all transparently fall through to a real call; a hit
# never outlives AUDIUS_SEARCH_CACHE_TTL_SECONDS. Plain Lock-guarded module
# state, the same idiom prompt_parser.py already uses for _ollama_slots /
# _last_ollama_call, not a new dependency.
AUDIUS_SEARCH_CACHE_TTL_SECONDS = float(os.getenv("AUDIUS_SEARCH_CACHE_TTL_SECONDS", "75"))
AUDIUS_SEARCH_CACHE_MAX_ENTRIES = int(os.getenv("AUDIUS_SEARCH_CACHE_MAX_ENTRIES", "200"))

_search_cache_lock = Lock()
# key -> (expires_at, results). Regular dicts preserve insertion order, which
# the oldest-first eviction in _cache_put relies on -- not a full LRU, just
# enough to keep this bounded without extra bookkeeping.
_search_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}

# Debug-panel observability only, mirroring prompt_parser's
# _last_ollama_call / get_last_ollama_call: whether the most recent
# search_tracks call in this process was served from cache. Never consulted
# by search_tracks itself -- only real calls update it.
_last_cache_lookup_lock = Lock()
_last_cache_lookup: dict = {"hit": None}


def _record_cache_lookup(hit: bool) -> None:
    with _last_cache_lookup_lock:
        _last_cache_lookup["hit"] = hit


def get_last_search_cache_hit() -> bool | None:
    """A shallow read so callers can't mutate the shared tracker. None means
    no search_tracks call has happened yet in this process."""

    with _last_cache_lookup_lock:
        return _last_cache_lookup["hit"]


def _cache_get(key: tuple[str, int]) -> list[dict] | None:
    with _search_cache_lock:
        entry = _search_cache.get(key)
        if entry is None:
            return None
        expires_at, results = entry
        if time.monotonic() >= expires_at:
            # Expired -- drop it so a stale entry never lingers past its TTL.
            del _search_cache[key]
            return None
        return results


def _cache_put(key: tuple[str, int], results: list[dict]) -> None:
    with _search_cache_lock:
        if key not in _search_cache and len(_search_cache) >= AUDIUS_SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(_search_cache))
            del _search_cache[oldest_key]
        _search_cache[key] = (time.monotonic() + AUDIUS_SEARCH_CACHE_TTL_SECONDS, results)


def _optional_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def get_artwork_url(artwork: dict | None) -> str | None:
    """
    Extract the best available artwork URL from Audius.

    Audius may return several image sizes:
    - 1000x1000
    - 480x480
    - 150x150

    We prefer the highest quality image.
    If no artwork exists, return None.
    """
    if not isinstance(artwork, dict):
        return None

    return _optional_text(
        artwork.get("1000x1000")
        or artwork.get("480x480")
        or artwork.get("150x150")
    )


def search_tracks(prompt: str, limit: int = 5) -> list[dict]:
    """
    Search Audius tracks by user prompt, served from a short-TTL cache when
    possible (see the cache section above) -- callers never need to know
    whether a given result came from cache or a live call.
    """

    key = (prompt, limit)
    try:
        cached = _cache_get(key)
    except Exception as exc:  # cache mechanics must never break retrieval
        cached = None
        logger.warning("Audius search cache lookup failed, calling Audius directly: %s", exc)

    if cached is not None:
        _record_cache_lookup(True)
        return cached

    results = _search_tracks_uncached(prompt, limit)

    _record_cache_lookup(False)
    # Only successful, non-empty results are cached: an empty list here is
    # indistinguishable from "Audius genuinely has nothing" and "the call
    # just failed" (_search_tracks_uncached returns [] for both), and
    # caching a transient-failure-shaped empty result would mean a brief
    # provider hiccup "poisons" this query for up to the full TTL instead of
    # the very next call recovering immediately.
    if results:
        try:
            _cache_put(key, results)
        except Exception as exc:  # a failed cache write must not affect the result
            logger.warning("Audius search cache store failed (result still returned): %s", exc)

    return results


def _search_tracks_uncached(prompt: str, limit: int = 5) -> list[dict]:
    """
    Search Audius tracks by user prompt.

    For now, this only returns track metadata + stream URL.
    Later, we will save these tracks into PostgreSQL.
    """

    params = {
        "query": prompt,
        "limit": limit,
        "app_name": APP_NAME,
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(6.0), follow_redirects=True) as client:
            response = client.get(
                f"{AUDIUS_API_BASE}/tracks/search",
                params=params,
            )
            response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        # Provider downtime must not turn session creation into a 500.  The
        # caller can select the licensed local demo fallback when this returns
        # an empty candidate list.
        logger.warning("Audius search failed: %s", exc)
        return []

    if not isinstance(data, dict):
        return []
    tracks = data.get("data", [])

    if not isinstance(tracks, list):
        return []

    results = []

    for track in tracks[:limit]:
        if not isinstance(track, dict):
            continue
        track_id = track.get("id")

        if isinstance(track_id, bool) or not isinstance(track_id, (str, int)):
            continue
        if isinstance(track_id, str) and not track_id.strip():
            continue

        user = track.get("user")
        if not isinstance(user, dict):
            user = {}

        try:
            duration = max(0, int(track.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0

        artwork_url = get_artwork_url(track.get("artwork"))
        if not isinstance(artwork_url, str):
            artwork_url = None
        safe_track_id = quote(str(track_id), safe="")

        results.append(
            {
                "source": "audius",
                "source_track_id": str(track_id),
                "title": _optional_text(track.get("title")) or "Unknown title",
                "artist": _optional_text(user.get("name")) or "Unknown artist",
                "duration": duration,
                "genre": _optional_text(track.get("genre")),
                "mood": _optional_text(track.get("mood")),
                "tags": _optional_text(track.get("tags")),
                "cover_url": artwork_url,
                "audio_url": f"{AUDIUS_API_BASE}/tracks/{safe_track_id}/stream?app_name={APP_NAME}",
            }
        )

    return results
