"""Optional Ollama-compatible prompt parser with a deterministic fallback.

The LLM may classify intent, but it is never allowed to invent playable
tracks.  Catalog candidates always come from Audius or the known local demo.
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
_llm_slots = BoundedSemaphore(max(1, min(16, int(os.getenv("OLLAMA_MAX_CONCURRENCY", "4")))))


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
        search_query=" ".join(text.split())[:120],
    )


def parse_prompt(prompt: str) -> PromptIntent:
    base_url = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip()
    fallback = deterministic_parse(prompt)
    if not base_url or not model:
        return fallback

    instruction = (
        "Classify this music request. Return JSON only with mood, energy "
        "(low|medium|high), vocals (less|neutral|more), genres (max 5), and "
        f"search_query. Request: {prompt!r}"
    )
    if not _llm_slots.acquire(timeout=0.05):
        return fallback
    try:
        timeout_seconds = max(0.5, min(10.0, float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "3.0"))))
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": instruction, "format": "json", "stream": False},
            )
            response.raise_for_status()
        payload = response.json()
        raw = payload.get("response") if isinstance(payload, dict) else None
        decoded = json.loads(raw) if isinstance(raw, str) else raw
        intent = PromptIntent.model_validate(decoded)
    except (httpx.HTTPError, ValueError, TypeError, ValidationError):
        return fallback
    finally:
        _llm_slots.release()

    # Only known genre labels can influence retrieval.  The user prompt remains
    # the source for the search text, preventing invented song names from being
    # promoted to catalog records.
    intent.genres = [genre.lower() for genre in intent.genres if genre.lower() in ALLOWED_GENRES]
    intent.search_query = fallback.search_query
    return intent
