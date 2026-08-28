"""Optional LLM-refined prompt parsing (Ollama) with a deterministic
fallback.

The LLM may classify intent, but it is never allowed to invent playable
tracks.  Catalog candidates always come from Audius or the known local demo.
Whether the VibeUnderstander in `pipeline.vibe` calls out to Ollama at all is
a startup-time choice made in `pipeline/dependencies.py`; `parse_prompt`
below falls back to `deterministic_parse` on its own whenever Ollama isn't
configured, unreachable, or returns something invalid.

Concurrency (D4): at most OLLAMA_MAX_CONCURRENCY calls are ever in flight
against Ollama at once; a call beyond that genuinely queues behind
OLLAMA_QUEUE_WAIT_SECONDS (a real wait, not the old 50ms shed) before
falling back to the deterministic parse. See get_ollama_stats() for the
attempted/succeeded/timeout/HTTP/invalid/unexpected/shed counters this
produces, and
get_cluster_ollama_stats() for the cross-replica aggregate.

D6b: that concurrency cap is enforced across every BACKEND_WORKERS replica,
not per-replica -- see _acquire_ollama_slot's own docstring for the
Redis-backed distributed semaphore this uses when Redis is configured
(falling back to the original process-local one otherwise).
"""

import json
import logging
import os
import re
from datetime import UTC, datetime
from threading import BoundedSemaphore, Lock
from time import monotonic, perf_counter, sleep, time
from uuid import uuid4

import httpx
import redis as sync_redis
from pydantic import ValidationError

from app.core.redis_client import get_sync_redis_client
from app.schemas import AutoMixMode, PromptIntent

logger = logging.getLogger(__name__)

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

# Literal proposal modes are an explicit user choice, not a phrase for the
# LLM/deterministic parser to guess. Applying one replaces only the musical
# dimensions controlled by the mode while preserving a parsed artist ask and
# the original safe search text. The same function is used by live sessions
# and persisted mixes so the four buttons cannot drift into different
# meanings across product surfaces.
AUTO_MIX_MODE_PRESETS: dict[AutoMixMode, dict[str, str | list[str]]] = {
    AutoMixMode.WORKOUT: {
        "mood": "energetic",
        "energy": "high",
        "vocals": "neutral",
        "genres": ["electronic", "hip-hop", "rock"],
    },
    AutoMixMode.RELAXATION: {
        "mood": "calm",
        "energy": "low",
        "vocals": "less",
        "genres": ["ambient", "lofi", "classical"],
    },
    AutoMixMode.EMOTIONAL_TARAB: {
        "mood": "emotional",
        "energy": "medium",
        "vocals": "more",
        "genres": ["arabic"],
    },
    AutoMixMode.PARTY: {
        "mood": "party",
        "energy": "high",
        "vocals": "more",
        "genres": ["pop", "house", "electronic"],
    },
}


def apply_auto_mix_mode(intent: PromptIntent, mode: AutoMixMode | None) -> PromptIntent:
    """Apply one explicit, deterministic product preset to a parsed intent."""

    if mode is None:
        return intent
    return intent.model_copy(update=AUTO_MIX_MODE_PRESETS[mode], deep=True)


# Process-local fallback only -- see _acquire_ollama_slot below for when
# this is actually used vs. the D6b distributed semaphore.
_ollama_slots = BoundedSemaphore(
    max(1, min(16, int(os.getenv("OLLAMA_MAX_CONCURRENCY", "4"))))
)


def _ollama_max_concurrency() -> int:
    return max(1, min(16, int(os.getenv("OLLAMA_MAX_CONCURRENCY", "4"))))


# D4: how long a call genuinely queues behind OLLAMA_MAX_CONCURRENCY's slots
# before giving up and falling back to the deterministic parser -- was a
# hardcoded 0.05s (a shed, not a queue: under load, nearly every request
# skipped the model entirely rather than waiting its turn). Clamped the same
# way OLLAMA_MAX_CONCURRENCY is just above.
OLLAMA_QUEUE_WAIT_SECONDS = max(
    0.05, min(10.0, float(os.getenv("OLLAMA_QUEUE_WAIT_SECONDS", "2.0")))
)

# D6b: without this, each BACKEND_WORKERS replica enforced its own local
# OLLAMA_MAX_CONCURRENCY independently, so the real concurrency against the
# one shared Ollama instance became `OLLAMA_MAX_CONCURRENCY * replica_count`
# -- silently defeating the whole point of the cap. A Redis sorted set holds
# one entry per currently-held slot, scored by that slot's own lease expiry
# (not by acquire time): acquiring atomically prunes expired leases before
# checking/adding (see _OLLAMA_SEMAPHORE_ACQUIRE_LUA), so a replica that
# crashes mid-call can never permanently shrink the cluster's real capacity
# -- its slot self-expires once its lease runs out rather than needing an
# explicit release that might never come. Used only when Redis is configured
# and reachable; _acquire_ollama_slot falls back to the original
# process-local _ollama_slots otherwise (same fail-open posture as every
# other Redis-backed feature in this codebase).
_OLLAMA_SEMAPHORE_KEY = "cuemix:ollama_semaphore"
_OLLAMA_SEMAPHORE_POLL_SECONDS = 0.05
# How long an acquired slot is leased for before it self-expires. The queue
# wait was already spent *before* acquiring, so this only needs to cover the
# actual model call: the lightweight parser caps at 20s while Studio's
# always-thinking reasoning path caps at 240s, plus slack for scheduling and
# network jitter around the release call itself.
_OLLAMA_LEASE_SECONDS = 270.0

# Atomic prune-then-acquire: two replicas racing this at once can never both
# see "room" and both add, since ZCARD is read and ZADD is written inside the
# same EVAL. Returns 1 (acquired) or 0 (still full after pruning expired
# leases).
_OLLAMA_SEMAPHORE_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local holder = ARGV[3]
local lease_expiry = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then
    return 0
end
redis.call('ZADD', key, lease_expiry, holder)
redis.call('EXPIRE', key, math.ceil(lease_expiry - now) + 5)
return 1
"""


def _acquire_distributed_slot(
    redis_client: sync_redis.Redis, timeout_seconds: float
) -> str | None:
    """Polls the Redis-backed distributed semaphore until a slot frees up or
    `timeout_seconds` elapses -- Redis has no native blocking-acquire
    primitive, so this is a bounded poll loop. Returns the holder token to
    release with, or None if the deadline passed without acquiring one (a
    genuine shed, same as the local-semaphore timeout path)."""

    holder = uuid4().hex
    limit = _ollama_max_concurrency()
    deadline = monotonic() + timeout_seconds
    while True:
        now = time()
        acquired = redis_client.eval(
            _OLLAMA_SEMAPHORE_ACQUIRE_LUA,
            1,
            _OLLAMA_SEMAPHORE_KEY,
            now,
            limit,
            holder,
            now + _OLLAMA_LEASE_SECONDS,
        )
        if acquired:
            return holder
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        sleep(min(_OLLAMA_SEMAPHORE_POLL_SECONDS, remaining))


def _release_distributed_slot(redis_client: sync_redis.Redis, holder: str) -> None:
    try:
        redis_client.zrem(_OLLAMA_SEMAPHORE_KEY, holder)
    except (sync_redis.RedisError, OSError):
        pass  # the lease self-expires regardless -- see _OLLAMA_LEASE_SECONDS


def _acquire_ollama_slot(timeout_seconds: float):
    """Returns a zero-arg release callback if a slot was acquired (the
    Redis-backed distributed semaphore when Redis is configured and
    reachable, else the original process-local BoundedSemaphore), or None
    if `timeout_seconds` elapsed without acquiring one -- a genuine shed.
    Callers must call the returned release callback exactly once, from a
    finally block, once the slot is no longer needed."""

    redis_client = get_sync_redis_client()
    if redis_client is not None:
        try:
            holder = _acquire_distributed_slot(redis_client, timeout_seconds)
        except (sync_redis.RedisError, OSError) as exc:
            logger.warning(
                "prompt_parser: distributed Ollama semaphore unavailable, "
                "falling back to process-local: %s",
                exc,
            )
        else:
            if holder is None:
                return None
            return lambda: _release_distributed_slot(redis_client, holder)

    if not _ollama_slots.acquire(timeout=timeout_seconds):
        return None
    return _ollama_slots.release


# Only create_session calls parse_prompt (see vibe.py/session_manager.py's
# own _initial_intent) -- apply_feedback/advance_session/prepare_next reuse
# the stored intent deterministically and never reach this module at all.
# /sessions/start's client-side timeout is 45s (frontend sessionApi.js);
# session_manager.AUDIO_RENDER_TIME_BUDGET_SECONDS already reserves up to
# 25s of that for render retries. 15s is a conservative slice of the
# remainder for this module's own queue-wait + actual model call combined --
# deliberately not the whole ~20s left, since retrieval/DB overhead isn't
# free either. Used only to clamp the *effective* queue wait below when an
# operator's OLLAMA_TIMEOUT_SECONDS is high enough that the configured
# OLLAMA_QUEUE_WAIT_SECONDS would otherwise risk pushing this stage past
# what the request can actually afford -- see parse_prompt.
_OLLAMA_STAGE_BUDGET_SECONDS = 15.0


def _ollama_keep_alive_payload(value: str | None = None) -> str | int:
    """Return the API representation Ollama expects for ``keep_alive``.

    Ollama accepts duration strings such as ``30m`` but its HTTP API requires
    sentinel values such as ``-1`` and ``0`` to be JSON numbers, not strings.
    Environment variables are always strings, so normalize only integer
    values and leave duration syntax untouched.
    """

    raw = (value if value is not None else os.getenv("OLLAMA_KEEP_ALIVE", "-1")).strip()
    try:
        return int(raw)
    except ValueError:
        return raw

# Debug-panel observability only (routers/debug.py): the outcome of the most
# recent actual Ollama call this process made. Never consulted by the parse
# path itself -- only real, attempted calls update it, so a disabled/unused
# LLM step correctly shows "no calls yet" rather than a stale/fabricated value.
_last_call_lock = Lock()
_last_ollama_call: dict = {"at": None, "latency_ms": None, "ok": None, "outcome": None}

_OLLAMA_OUTCOME_SUCCESS = "success"
_OLLAMA_OUTCOME_TIMEOUT = "timeout"
_OLLAMA_OUTCOME_HTTP_ERROR = "http_error"
_OLLAMA_OUTCOME_INVALID_RESPONSE = "invalid_response"
_OLLAMA_OUTCOME_UNEXPECTED_ERROR = "unexpected_error"
_OLLAMA_OUTCOMES = {
    _OLLAMA_OUTCOME_SUCCESS,
    _OLLAMA_OUTCOME_TIMEOUT,
    _OLLAMA_OUTCOME_HTTP_ERROR,
    _OLLAMA_OUTCOME_INVALID_RESPONSE,
    _OLLAMA_OUTCOME_UNEXPECTED_ERROR,
}

# Cumulative, process-level counters -- same lock as _last_ollama_call, same
# "only real attempted calls update it" rule. Per-process, not per-cluster --
# see get_cluster_ollama_stats() below (D6b) for the cross-replica
# aggregate; this one stays useful even with that available, e.g. "is THIS
# specific replica seeing timeouts." Latency is tracked as a running
# count/sum/max (not a list) so memory stays flat no matter how many calls a
# long-lived process makes.
_ollama_stats: dict = {
    "attempted": 0,
    "succeeded": 0,
    "timed_out": 0,
    "http_errors": 0,
    "invalid_responses": 0,
    "unexpected_errors": 0,
    "shed": 0,
    "latency_count": 0,
    "latency_sum_ms": 0.0,
    "latency_max_ms": 0.0,
}

# D6b: the cluster-wide counterpart to _ollama_stats above, a Redis hash
# every replica increments so the debug panel can show one real cluster-wide
# view instead of only whichever replica happened to serve that particular
# GET /debug/pipeline request. Best-effort, fire-and-forget: a failed
# increment here never affects the parse_prompt call it's describing (see
# _record_ollama_call/_record_ollama_shed's own try/except), same fail-open
# posture as the rest of this module's Redis usage.
_OLLAMA_CLUSTER_STATS_KEY = "cuemix:ollama_stats"


def _record_cluster_ollama_call(latency_ms: float, outcome: str) -> None:
    redis_client = get_sync_redis_client()
    if redis_client is None:
        return
    try:
        redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "attempted", 1)
        if outcome == _OLLAMA_OUTCOME_SUCCESS:
            redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "succeeded", 1)
            redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "latency_count", 1)
            redis_client.hincrbyfloat(
                _OLLAMA_CLUSTER_STATS_KEY, "latency_sum_ms", latency_ms
            )
            # Best-effort high-watermark, not atomic against a concurrent
            # writer on another replica -- a lost race here just means the
            # displayed max briefly undercounts the true slowest call, not a
            # correctness problem for anything that reads this value. An
            # atomic version would need a Lua compare-and-set; not obviously
            # worth it for a display-only "slowest call we've seen" metric.
            current_max = float(
                redis_client.hget(_OLLAMA_CLUSTER_STATS_KEY, "latency_max_ms") or 0.0
            )
            if latency_ms > current_max:
                redis_client.hset(
                    _OLLAMA_CLUSTER_STATS_KEY, "latency_max_ms", latency_ms
                )
        elif outcome == _OLLAMA_OUTCOME_TIMEOUT:
            redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "timed_out", 1)
        elif outcome == _OLLAMA_OUTCOME_HTTP_ERROR:
            redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "http_errors", 1)
        elif outcome == _OLLAMA_OUTCOME_INVALID_RESPONSE:
            redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "invalid_responses", 1)
        else:
            redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "unexpected_errors", 1)
    except (sync_redis.RedisError, OSError):
        logger.debug(
            "prompt_parser: cluster Ollama stats increment failed", exc_info=True
        )


def _record_cluster_ollama_shed() -> None:
    redis_client = get_sync_redis_client()
    if redis_client is None:
        return
    try:
        redis_client.hincrby(_OLLAMA_CLUSTER_STATS_KEY, "shed", 1)
    except (sync_redis.RedisError, OSError):
        logger.debug(
            "prompt_parser: cluster Ollama shed increment failed", exc_info=True
        )


def _record_ollama_call(latency_ms: float, outcome: str) -> None:
    if outcome not in _OLLAMA_OUTCOMES:
        raise ValueError(f"Unknown Ollama outcome: {outcome}")
    with _last_call_lock:
        _last_ollama_call["at"] = datetime.now(UTC).replace(tzinfo=None)
        _last_ollama_call["latency_ms"] = round(latency_ms, 1)
        _last_ollama_call["ok"] = outcome == _OLLAMA_OUTCOME_SUCCESS
        _last_ollama_call["outcome"] = outcome
        _ollama_stats["attempted"] += 1
        if outcome == _OLLAMA_OUTCOME_SUCCESS:
            _ollama_stats["succeeded"] += 1
            _ollama_stats["latency_count"] += 1
            _ollama_stats["latency_sum_ms"] += latency_ms
            _ollama_stats["latency_max_ms"] = max(
                _ollama_stats["latency_max_ms"], latency_ms
            )
        elif outcome == _OLLAMA_OUTCOME_TIMEOUT:
            _ollama_stats["timed_out"] += 1
        elif outcome == _OLLAMA_OUTCOME_HTTP_ERROR:
            _ollama_stats["http_errors"] += 1
        elif outcome == _OLLAMA_OUTCOME_INVALID_RESPONSE:
            _ollama_stats["invalid_responses"] += 1
        else:
            _ollama_stats["unexpected_errors"] += 1
    _record_cluster_ollama_call(latency_ms, outcome)


def _record_ollama_shed() -> None:
    """The semaphore-acquire timeout expired before a request was even
    issued -- distinct from `attempted`, which only counts calls that
    actually reached Ollama (or timed out doing so)."""

    with _last_call_lock:
        _ollama_stats["shed"] += 1
    _record_cluster_ollama_shed()


def get_last_ollama_call() -> dict:
    """A shallow copy so callers can't mutate the shared tracker."""

    with _last_call_lock:
        return dict(_last_ollama_call)


def get_ollama_stats() -> dict:
    """Cumulative, per-process counters plus derived success rate / mean
    latency. A copy under the lock, same reasoning as get_last_ollama_call.
    See get_cluster_ollama_stats() for the cross-replica aggregate."""

    with _last_call_lock:
        stats = dict(_ollama_stats)
    attempted = stats["attempted"]
    stats["success_rate"] = (stats["succeeded"] / attempted) if attempted else None
    latency_count = stats["latency_count"]
    stats["mean_latency_ms"] = (
        round(stats["latency_sum_ms"] / latency_count, 1) if latency_count else None
    )
    return stats


def get_cluster_ollama_stats() -> dict | None:
    """The same shape get_ollama_stats() returns (minus latency_max_ms,
    which callers of get_ollama_stats() don't read either -- both compute
    their derived fields from the same latency_count/latency_sum_ms pair),
    aggregated across every replica via the Redis hash
    _record_cluster_ollama_call/_record_cluster_ollama_shed write to. None
    when Redis isn't configured or unreachable -- routers/debug.py falls
    back to presenting only the per-process numbers in that case, the same
    thing this whole module already did before D6b."""

    redis_client = get_sync_redis_client()
    if redis_client is None:
        return None
    try:
        raw = redis_client.hgetall(_OLLAMA_CLUSTER_STATS_KEY)
    except (sync_redis.RedisError, OSError):
        return None
    attempted = int(raw.get("attempted", 0))
    succeeded = int(raw.get("succeeded", 0))
    latency_count = int(raw.get("latency_count", 0))
    latency_sum_ms = float(raw.get("latency_sum_ms", 0.0))
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "timed_out": int(raw.get("timed_out", 0)),
        "http_errors": int(raw.get("http_errors", 0)),
        "invalid_responses": int(raw.get("invalid_responses", 0)),
        "unexpected_errors": int(raw.get("unexpected_errors", 0)),
        "shed": int(raw.get("shed", 0)),
        "success_rate": (succeeded / attempted) if attempted else None,
        "mean_latency_ms": round(latency_sum_ms / latency_count, 1)
        if latency_count
        else None,
    }


def reset_ollama_stats() -> None:
    """Test-only: clears cumulative counters (both the process-local ones
    and, when Redis is configured, the cluster-wide Redis hash) so cases
    don't leak into each other. Never called from application code."""

    with _last_call_lock:
        _ollama_stats.update(
            {
                "attempted": 0,
                "succeeded": 0,
                "timed_out": 0,
                "http_errors": 0,
                "invalid_responses": 0,
                "unexpected_errors": 0,
                "shed": 0,
                "latency_count": 0,
                "latency_sum_ms": 0.0,
                "latency_max_ms": 0.0,
            }
        )
    redis_client = get_sync_redis_client()
    if redis_client is not None:
        try:
            redis_client.delete(_OLLAMA_CLUSTER_STATS_KEY)
        except (sync_redis.RedisError, OSError):
            pass


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
        "some",
        "something",
        "music",
        "songs",
        "tracks",
        "a",
        "the",
        "for",
        "me",
        "and",
        "of",
        "please",
    }
    meaningful = words - filler
    if not meaningful:
        return True
    keyword_like = (
        ALLOWED_GENRES
        | _HIGH_ENERGY_WORDS
        | _LOW_ENERGY_WORDS
        | {
            "vocals",
            "instrumental",
            "less",
            "vibes",
            "vibe",
            "mix",
            "beats",
        }
    )
    return meaningful <= keyword_like


def _extract_artist_and_mode(prompt: str) -> tuple[str | None, str]:
    """Regex-only artist detection: which trigger phrase matched decides
    artist_mode, not a guess about intent. When both a required- and a
    reference-style trigger match the same prompt, whichever one starts
    earlier (the more leading, and so presumably primary, phrase) wins."""

    required_match = _ARTIST_REQUIRED_PATTERN.search(prompt)
    reference_match = _ARTIST_REFERENCE_PATTERN.search(prompt)

    if required_match and (
        not reference_match or required_match.start() <= reference_match.start()
    ):
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
    energy = (
        "high"
        if tokens & _HIGH_ENERGY_WORDS
        else "low"
        if tokens & _LOW_ENERGY_WORDS
        else "medium"
    )
    vocals = (
        "less"
        if {"instrumental", "focus", "less"} & tokens
        else "more"
        if "vocals" in tokens
        else "neutral"
    )
    genres = sorted(tokens & ALLOWED_GENRES)[:5]
    mood = next(
        (
            word
            for word in ("energetic", "calm", "chill", "focus", "smooth")
            if word in tokens
        ),
        "balanced",
    )
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

    intent.genres = [
        genre.lower() for genre in intent.genres if genre.lower() in ALLOWED_GENRES
    ]
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

    fallback = deterministic_parse(prompt)
    if fallback.artist_mode == "required" and fallback.artist:
        # QueryPlanner already prioritizes the artist alone in this case
        # (build_queries' required_artist branch), regardless of whatever
        # mood/energy/genres the LLM would additionally refine -- calling
        # Ollama here is pure wasted latency. Every other case (genre-only,
        # vibe-only, reference-mode, no artist) still gets refined normally;
        # those are exactly where the LLM materially helps.
        return fallback

    base_url = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip()
    if not base_url or not model:
        return fallback

    timeout_seconds = max(
        0.5, min(20.0, float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "3.0")))
    )
    # See _OLLAMA_STAGE_BUDGET_SECONDS's own docstring: normally a no-op
    # (OLLAMA_QUEUE_WAIT_SECONDS's default plus OLLAMA_TIMEOUT_SECONDS's own
    # default comfortably fit under the budget), this only actually clamps
    # the wait down when an operator's configured OLLAMA_TIMEOUT_SECONDS
    # eats far enough into the shared stage budget that the configured queue
    # wait would risk pushing this call past what the request can afford.
    queue_wait_seconds = min(
        OLLAMA_QUEUE_WAIT_SECONDS,
        max(0.05, _OLLAMA_STAGE_BUDGET_SECONDS - timeout_seconds),
    )
    release_slot = _acquire_ollama_slot(queue_wait_seconds)
    if release_slot is None:
        _record_ollama_shed()
        return fallback
    # Everything from here down runs only once a slot was actually acquired
    # -- both _record_ollama_call and the release below live in this same
    # try/finally, so every acquired call (success, timeout, HTTP/validation
    # failure, or a genuinely unexpected exception) always releases exactly
    # once; the shed path above never acquired, so it has nothing to
    # release.
    started = perf_counter()
    outcome = _OLLAMA_OUTCOME_UNEXPECTED_ERROR
    try:
        # Qwen3 models default to "thinking mode" on in Ollama, which emits a
        # hidden reasoning block before the real answer and adds real latency
        # to this classification-only call -- off by default here since
        # that's the safer choice until a given deployment's GPU is confirmed
        # to handle it within OLLAMA_TIMEOUT_SECONDS; flip per-environment via
        # the env var alone, no code change needed.
        think_enabled = os.getenv("OLLAMA_THINK_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        # Ollama unloads an idle model from memory after its keep-alive window
        # (5 minutes by default), so a request after any gap pays a full
        # reload-from-disk before it can even start generating. A per-request
        # "keep_alive" overrides the server-level default on every call,
        # refreshing the timer on each real use on top of the container-level
        # OLLAMA_KEEP_ALIVE setting. Duration syntax stays a string, while
        # integer sentinels are normalized to JSON numbers for Ollama's API.
        keep_alive = _ollama_keep_alive_payload()
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
                    "think": think_enabled,
                    "keep_alive": keep_alive,
                },
            )
            response.raise_for_status()
        payload = response.json()
        raw = payload.get("response") if isinstance(payload, dict) else None
        decoded = json.loads(raw) if isinstance(raw, str) else raw
        intent = PromptIntent.model_validate(decoded)
        outcome = _OLLAMA_OUTCOME_SUCCESS
    except httpx.TimeoutException:
        outcome = _OLLAMA_OUTCOME_TIMEOUT
        return fallback
    except httpx.HTTPError:
        outcome = _OLLAMA_OUTCOME_HTTP_ERROR
        return fallback
    except (ValueError, TypeError, ValidationError):
        outcome = _OLLAMA_OUTCOME_INVALID_RESPONSE
        return fallback
    except Exception:
        # Preserve the parser's fail-open contract, but keep operational
        # failures distinct from actual network timeouts in the dashboard.
        logger.warning("Unexpected Ollama prompt-refinement failure", exc_info=True)
        outcome = _OLLAMA_OUTCOME_UNEXPECTED_ERROR
        return fallback
    finally:
        _record_ollama_call((perf_counter() - started) * 1000, outcome)
        release_slot()

    return _apply_guardrails(intent, fallback)
