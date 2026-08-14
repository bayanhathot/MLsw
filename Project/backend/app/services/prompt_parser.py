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
from datetime import UTC, datetime
from threading import BoundedSemaphore, Lock
from time import perf_counter

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

# Debug-panel observability only (routers/debug.py): the outcome of the most
# recent actual Ollama call this process made. Never consulted by the parse
# path itself -- only real, attempted calls update it, so a disabled/unused
# LLM step correctly shows "no calls yet" rather than a stale/fabricated value.
_last_call_lock = Lock()
_last_ollama_call: dict = {"at": None, "latency_ms": None, "ok": None}


def _record_ollama_call(latency_ms: float, ok: bool) -> None:
    with _last_call_lock:
        _last_ollama_call["at"] = datetime.now(UTC).replace(tzinfo=None)
        _last_ollama_call["latency_ms"] = round(latency_ms, 1)
        _last_ollama_call["ok"] = ok


def get_last_ollama_call() -> dict:
    """A shallow copy so callers can't mutate the shared tracker."""

    with _last_call_lock:
        return dict(_last_ollama_call)

_HIGH_ENERGY_WORDS = {"energy", "energetic", "gym", "workout", "fast", "intense"}
_LOW_ENERGY_WORDS = {"calm", "chill", "focus", "relax", "smooth", "sleep"}

# Two separate artist triggers, not one: "required" means the user wants
# that exact artist's own tracks (a hard ask), "reference" means a stylistic
# pointer ("something that sounds like X") that shouldn't be treated as a
# hard requirement for that specific artist. Both are only ever a hint to
# CandidateRetriever -- an unmatched or wrong extraction just means no
# artist-flavored query gets built, never an invented catalog entry.
#
# The generic "by <name>" branch (no leading "songs"/"music") is kept
# deliberately broad, not narrowed to "songs by"/"music by" only, so prompts
# like "chill vibes by Nova Blackwood" keep resolving an artist the way they
# always have. The bare "play <name>" branch is new -- it's what "play
# george wassouf" needed and had no trigger phrase for at all before -- and
# is guarded separately in _extract_artist_and_mode against swallowing a
# vibe description that merely happens to start with "play" (see
# _looks_like_vibe_description).
_ARTIST_REQUIRED_PATTERN = re.compile(
    r"\bplay\s+some\s+(?P<play_some_music>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60}?)\s+music\b"
    r"|\bput\s+on\s+(?P<put_on>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
    r"|\bsongs\s+by\s+(?P<songs_by>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
    r"|\bmusic\s+by\s+(?P<music_by>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
    r"|\bmusic\s+from\s+(?P<music_from>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
    r"|\bgive\s+me\s+some\s+(?P<give_me_some>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
    r"|\bby\s+(?P<by_bare>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})"
    r"|\bplay\s+(?P<play_bare>[A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})$",
    re.IGNORECASE,
)
_ARTIST_REFERENCE_PATTERN = re.compile(
    r"\b(?:something\s+like|similar\s+to|reminds?\s+me\s+of)\s+([A-Za-z0-9][A-Za-z0-9 &'.-]{1,60})",
    re.IGNORECASE,
)
_ARTIST_STOP_WORDS = re.compile(r"\b(?:but|and|for|with|that|which)\b", re.IGNORECASE)


def _clean_candidate(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = _ARTIST_STOP_WORDS.split(raw, maxsplit=1)[0]
    candidate = candidate.strip(" .,'-")
    return candidate[:120] or None


def _first_group(match: re.Match) -> str | None:
    return next((value for value in match.groupdict().values() if value), None)


def _looks_like_vibe_description(candidate: str) -> bool:
    """Guards the two "play"-prefixed required triggers only (bare "play X"
    and "play some X music"): unlike every other required-artist trigger
    ("songs by", "music from", ...), "play" is also how a vibe description
    often starts ("play some upbeat electronic music", "play something
    chill and relaxing"), and a real artist name is unlikely to be made up
    entirely of the same genre/mood/energy vocabulary deterministic_parse
    already reads from the raw prompt. Rejecting that case here keeps a
    vibe-only prompt from hijacking retrieval as a required-artist search
    for that phrase."""

    words = set(re.findall(r"[a-z0-9-]+", candidate.lower()))
    filler = {
        "some", "something", "music", "songs", "tracks", "a", "the", "for",
        "me", "and", "of", "please",
    }
    meaningful = words - filler
    if not meaningful:
        return True
    keyword_like = ALLOWED_GENRES | _HIGH_ENERGY_WORDS | _LOW_ENERGY_WORDS | {
        "vocals", "instrumental", "less", "vibes", "vibe", "mix", "beats",
    }
    return meaningful <= keyword_like


def _extract_artist_and_mode(prompt: str) -> tuple[str | None, str]:
    """Regex-only artist detection: which trigger phrase matched decides
    artist_mode, not a guess about intent. When both a required- and a
    reference-style trigger match the same prompt, whichever one starts
    earlier (the more leading, and so presumably primary, phrase) wins."""

    required_match = _ARTIST_REQUIRED_PATTERN.search(prompt)
    reference_match = _ARTIST_REFERENCE_PATTERN.search(prompt)

    if required_match and (not reference_match or required_match.start() <= reference_match.start()):
        candidate = _clean_candidate(_first_group(required_match))
        if candidate is None:
            return None, "none"
        groups = required_match.groupdict()
        is_play_prefixed = groups.get("play_bare") or groups.get("play_some_music")
        if is_play_prefixed:
            # "play X" / "play some X music" greedily swallow a reference
            # trigger that immediately follows "play" too ("play something
            # like Drake" -> candidate="something like Drake"), since
            # nothing in either pattern stops "play" from being followed by
            # one. Re-extract as a reference match when the captured
            # candidate itself starts with one of those trigger phrases,
            # rather than treating the whole "something like Drake" string
            # as a required-mode artist name.
            embedded_reference = _ARTIST_REFERENCE_PATTERN.match(candidate)
            if embedded_reference:
                inner_candidate = _clean_candidate(embedded_reference.group(1))
                if inner_candidate is None:
                    return None, "none"
                return inner_candidate, "reference"
            if _looks_like_vibe_description(candidate):
                return None, "none"
        return candidate, "required"

    if reference_match:
        candidate = _clean_candidate(reference_match.group(1))
        if candidate is None:
            return None, "none"
        return candidate, "reference"

    return None, "none"


def deterministic_parse(prompt: str) -> PromptIntent:
    text = prompt.strip().lower()
    tokens = set(re.findall(r"[a-z0-9-]+", text))
    energy = "high" if tokens & _HIGH_ENERGY_WORDS else "low" if tokens & _LOW_ENERGY_WORDS else "medium"
    vocals = "less" if {"instrumental", "focus", "less"} & tokens else "more" if "vocals" in tokens else "neutral"
    genres = sorted(tokens & ALLOWED_GENRES)[:5]
    mood = next((word for word in ("energetic", "calm", "chill", "focus", "smooth") if word in tokens), "balanced")
    artist, artist_mode = _extract_artist_and_mode(prompt)
    return PromptIntent(
        mood=mood,
        energy=energy,
        vocals=vocals,
        genres=genres,
        artist=artist,
        artist_mode=artist_mode,
        search_query=" ".join(text.split())[:120],
    )


def _refinement_instruction(prompt: str) -> str:
    return (
        "Classify this music request: mood, energy, vocals, up to 5 genres, an "
        "optional artist name the user explicitly mentioned (or null), an "
        "artist_mode ('required' if the user wants that exact artist's own "
        "tracks, 'reference' if it's only a stylistic comparison, or 'none' "
        "if no artist was named), and a search_query. "
        f"Request: {prompt!r}"
    )


def _apply_guardrails(intent: PromptIntent, fallback: PromptIntent) -> PromptIntent:
    """Confines an LLM's structured guess to refining classification only.

    Only known genre labels can influence retrieval.  The user prompt remains
    the source for the search text, preventing invented song names from being
    promoted to catalog records. The regex-extracted artist wins over the
    LLM's guess for the same reason; the LLM's guess is only used when the
    deterministic pass found nothing. artist_mode always tracks whichever
    artist source actually won -- never the LLM's mode paired with a
    different (regex-extracted) artist. parse_prompt (Ollama) applies this
    before returning, so the LLM can never override anything
    CandidateRetriever depends on.
    """

    intent.genres = [genre.lower() for genre in intent.genres if genre.lower() in ALLOWED_GENRES]
    intent.search_query = fallback.search_query
    llm_artist = intent.artist.strip() if isinstance(intent.artist, str) else None
    if fallback.artist:
        intent.artist = fallback.artist
        intent.artist_mode = fallback.artist_mode
    elif llm_artist:
        intent.artist = llm_artist
        # intent.artist_mode is already one of the three literals here --
        # Pydantic validated it when `intent` was parsed from the LLM's JSON
        # response, the same safety net genres/energy/vocals already rely on.
    else:
        intent.artist = None
        intent.artist_mode = "none"
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
    started = perf_counter()
    ok = False
    try:
        timeout_seconds = max(0.5, min(20.0, float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "3.0"))))
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
        ok = True
    except (httpx.HTTPError, ValueError, TypeError, ValidationError):
        return fallback
    finally:
        _record_ollama_call((perf_counter() - started) * 1000, ok)
        _ollama_slots.release()

    return _apply_guardrails(intent, fallback)
