"""
Audius service for Zonix.

This service is responsible for communicating with the external Audius API.

Why this file exists:
- The router should not directly contain external API logic.
- This file keeps Audius-specific code separated from FastAPI route code.
- The rest of the backend can call search_tracks() without knowing the raw Audius API format.

Current MVP behavior:
1. Receive a user prompt, for example: "chill electronic focus".
2. Send the prompt to Audius track search.
3. Receive raw Audius track data.
4. Extract only the fields Zonix needs:
   - track id
   - title
   - artist
   - duration
   - cover image
   - stream URL
5. Return a clean list of track dictionaries.

Important:
This service does not create real song segments yet.
It only fetches candidate tracks. The mix router later converts each track
into a simple 45-second segment for the MVP.

Future improvements:
- Add better prompt-to-tag mapping.
- Filter by genre, mood, or duration.
- Handle Audius provider failures more gracefully.
- Save fetched tracks into PostgreSQL.
- Use real audio analysis to find the best song moments.
"""

import logging
from urllib.parse import quote

import httpx

# Base URL for the Audius Discovery API.
# We use it to search for tracks and build playable stream URLs.
AUDIUS_API_BASE = "https://discoveryprovider.audius.co/v1"
APP_NAME = "Zonix"
logger = logging.getLogger(__name__)


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
