"""Optional LLM-refined prompt parsing (Ollama) with a deterministic
fallback.

The LLM may classify intent, but it is never allowed to invent playable
tracks.  Catalog candidates always come from Audius or the known local demo.
Whether the VibeUnderstander in `pipeline.vibe` calls out to Ollama at all is
a startup-time choice made in `pipeline/dependencies.py`; `parse_prompt`
below falls back to `deterministic_parse` on its own whenever Ollama isn't
configured, unreachable, or returns something invalid.
"""

import json
import os
import re
from threading import BoundedSemaphore

import httpx
from pydantic import ValidationError

from app.schemas import PromptIntent

ALLOWED_GENRES = {
    "ambient",
    "arabic",
    "classical",
    "electronic",
    "hip-hop",
    "house",
    "jazz",
    "lofi",
    "pop",
    "rock",
    "techno",
}
_ollama_slots = BoundedSemaphore(max(1, min(16, int(os.getenv("OLLAMA_MAX_CONCURRENCY", "4")))))

# Matches "by/like/similar to/reminds me of <name>" so a named artist can be
# forwarded to CandidateRetriever's fuzzy catalog search. This is only ever a
# hint: unmatched or wrong extractions just mean no fuzzy match is attempted,
# never an invented catalog entry.
_ARTIST_PATTERN = re.compile(
    r"\b(?:by|like|similar to|reminds? me of)\s+([A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
)
_ARTIST_STOP_WORDS = re.compile(r"\b(?:but|and|for|with|that|which)\b", re.IGNORECASE)


def _extract_artist(prompt: str) -> str | None:
    match = _ARTIST_PATTERN.search(prompt)
    if not match:
        return None
    candidate = _ARTIST_STOP_WORDS.split(match.group(1), maxsplit=1)[0]
    candidate = candidate.strip(" .,'-")
    return candidate[:120] or None


def deterministic_parse(prompt: str) -> PromptIntent:
    text = prompt.strip().lower()
    high_words = {"energy", "energetic", "gym", "workout", "fast", "intense"}
    low_words = {"calm", "chill", "focus", "relax", "smooth", "sleep"}
    tokens = set(re.findall(r"[a-z0-9-]+", text))
    energy = "high" if tokens & high_words else "low" if tokens & low_words else "medium"
    vocals = "less" if {"instrumental", "focus", "less"} & tokens else "more" if "vocals" in tokens else "neutral"
    genres = sorted(tokens & ALLOWED_GENRES)[:5]
    mood = next((word for word in ("energetic", "calm", "chill", "focus", "smooth") if word in tokens), "balanced")
    return PromptIntent(
        mood=mood,
        energy=energy,
        vocals=vocals,
        genres=genres,
        artist=_extract_artist(prompt),
        search_query=" ".join(text.split())[:120],
    )


def _refinement_instruction(prompt: str) -> str:
    return (
        "Classify this music request: mood, energy, vocals, up to 5 genres, an "
        "optional artist name the user explicitly mentioned (or null), and a "
        f"search_query. Request: {prompt!r}"
    )


def _apply_guardrails(intent: PromptIntent, fallback: PromptIntent) -> PromptIntent:
    """Confines an LLM's structured guess to refining classification only.

    Only known genre labels can influence retrieval.  The user prompt remains
    the source for the search text, preventing invented song names from being
    promoted to catalog records. The regex-extracted artist wins over the
    LLM's guess for the same reason; the LLM's guess is only used when the
    deterministic pass found nothing. parse_prompt (Ollama) applies this
    before returning, so the LLM can never override anything
    CandidateRetriever depends on.
    """

    intent.genres = [genre.lower() for genre in intent.genres if genre.lower() in ALLOWED_GENRES]
    intent.search_query = fallback.search_query
    llm_artist = intent.artist.strip() if isinstance(intent.artist, str) else None
    intent.artist = fallback.artist or (llm_artist or None)
    return intent


def parse_prompt(prompt: str) -> PromptIntent:
    """Deterministic parse, optionally refined by a local Ollama model."""

    base_url = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip()
    fallback = deterministic_parse(prompt)
    if not base_url or not model:
        return fallback

    if not _ollama_slots.acquire(timeout=0.05):
        return fallback
    try:
        timeout_seconds = max(0.5, min(10.0, float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "3.0"))))
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": _refinement_instruction(prompt),
                    # A JSON schema (rather than the bare "json" mode) makes
                    # Ollama constrain decoding to this shape, so the response
                    # is structurally guaranteed valid, not just instructed.
                    "format": PromptIntent.model_json_schema(),
                    "stream": False,
                },
            )
            response.raise_for_status()
        payload = response.json()
        raw = payload.get("response") if isinstance(payload, dict) else None
        decoded = json.loads(raw) if isinstance(raw, str) else raw
        intent = PromptIntent.model_validate(decoded)
    except (httpx.HTTPError, ValueError, TypeError, ValidationError):
        return fallback
    finally:
        _ollama_slots.release()

    return _apply_guardrails(intent, fallback)
