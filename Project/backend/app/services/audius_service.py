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
- Replace the temporary keyword fallback with LLM-based intent extraction.
- Filter by genre, mood, or duration.
- Handle Audius provider failures more gracefully.
- Save fetched tracks into PostgreSQL.
- Use real audio analysis to find the best song moments.
"""

import httpx

# Base URL for the Audius Discovery API.
# We use it to search for tracks and build playable stream URLs.
AUDIUS_API_BASE = "https://discoveryprovider.audius.co/v1"
APP_NAME = "Zonix"


# Audius search works best with short music-oriented queries. These rules are
# an MVP bridge between a natural-language DJ request and Audius search. They
# will be replaced by an LLM intent extractor later.
FALLBACK_QUERY_RULES = (
    ({"gym", "workout", "energy", "energetic"}, "workout electronic"),
    ({"coding", "focus", "work", "study"}, "chill electronic"),
    ({"arabic", "vocals", "vocal"}, "arabic"),
    ({"chill", "relax", "relaxing", "calm"}, "chill electronic"),
)


def build_search_queries(prompt: str) -> list[str]:
    """Build ordered Audius queries from a natural-language DJ prompt.

    The original prompt is always attempted first. If it produces no tracks,
    a short keyword-based query is attempted next. Returning an ordered list
    keeps the fallback behavior explicit and easy to replace with an LLM later.
    """

    normalized_prompt = prompt.casefold()
    queries = [prompt]

    for keywords, fallback_query in FALLBACK_QUERY_RULES:
        if any(keyword in normalized_prompt for keyword in keywords):
            if fallback_query not in queries:
                queries.append(fallback_query)
            break

    return queries


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
    if not artwork:
        return None

    return (
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

    tracks = []
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for query in build_search_queries(prompt):
            response = client.get(
                f"{AUDIUS_API_BASE}/tracks/search",
                params={
                    "query": query,
                    "limit": limit,
                    "app_name": APP_NAME,
                },
            )
            response.raise_for_status()

            tracks = response.json().get("data", [])
            if tracks:
                break

    results = []

    for track in tracks:
        track_id = track.get("id")

        if not track_id:
            continue

        user = track.get("user") or {}

        results.append(
            {
                "source": "audius",
                "source_track_id": track_id,
                "title": track.get("title", "Unknown title"),
                "artist": user.get("name", "Unknown artist"),
                "duration": track.get("duration", 0),
                "genre": track.get("genre"),
                "mood": track.get("mood"),
                "tags": track.get("tags"),
                "cover_url": get_artwork_url(track.get("artwork")),
                "audio_url": f"{AUDIUS_API_BASE}/tracks/{track_id}/stream?app_name={APP_NAME}",
            }
        )

    return results
