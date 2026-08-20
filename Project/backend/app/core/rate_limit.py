"""Sliding-window limiter for abuse-prone endpoints.

D6b: Redis-backed (via app.core.redis_client's sync client) so the limit is
shared across BACKEND_WORKERS replicas -- without this, each replica kept its
own process-local counter, so the effective limit was `requests * replica
count`, not `requests`. Falls back to the original process-local deque
whenever REDIS_URL is unconfigured (unchanged single-instance/test/dev
behavior) or a real Redis call fails (the same fail-open posture every other
Redis-backed feature in this codebase already has -- see redis_client.py's
own module docstring): a hiccup in the rate limiter must never turn into an
outage, and per-replica-only limiting in that narrow window is strictly
better than either no limiting or a hard failure.
"""

from collections import deque
import logging
import os
from threading import Lock
from time import monotonic, time
from uuid import uuid4

import redis as sync_redis
from fastapi import HTTPException, Request, status

from app.core.redis_client import get_sync_redis_client

logger = logging.getLogger(__name__)

# Atomic sliding-window check-and-record: prunes any entry older than the
# window, then only records the new one if the pruned count is still under
# the limit -- a single EVAL call so no two replicas can race a plain
# GET-then-SET/ZCARD-then-ZADD into both allowing a request that pushes the
# window over the limit. Returns 1 (allowed, recorded) or 0 (rejected, NOT
# recorded -- a rejected request must not itself count against the window).
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) >= limit then
    return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
return 1
"""


class RateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        # Process-local fallback -- see module docstring for when this path
        # is actually used.
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._last_prune = monotonic()

    def __call__(self, request: Request) -> None:
        forwarded = ""
        if os.getenv("TRUST_PROXY_HEADERS", "false").lower() in {"1", "true", "yes"}:
            # Enable only when all direct traffic is forced through a trusted
            # reverse proxy that replaces (rather than appends to) this header.
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        client_identity = forwarded or (request.client.host if request.client else "unknown")
        matched_route = request.scope.get("route")
        route_template = getattr(matched_route, "path", request.url.path)
        key = f"{route_template}:{client_identity}"

        redis_client = get_sync_redis_client()
        if redis_client is not None:
            try:
                allowed = self._check_redis(redis_client, key)
            except (sync_redis.RedisError, OSError) as exc:
                logger.warning("rate_limit: Redis check failed, falling back to process-local: %s", exc)
            else:
                if not allowed:
                    self._reject()
                return

        self._check_local(key)

    def _check_redis(self, redis_client: sync_redis.Redis, key: str) -> bool:
        now = time()
        result = redis_client.eval(
            _SLIDING_WINDOW_LUA,
            1,
            f"cuemix:ratelimit:{key}",
            now,
            self.window_seconds,
            self.requests,
            f"{now}-{uuid4().hex}",
        )
        return bool(result)

    def _check_local(self, key: str) -> None:
        now = monotonic()
        with self._lock:
            # Periodically discard inactive identities so attacker-controlled
            # client addresses cannot grow this process-local map forever.
            if now - self._last_prune >= min(self.window_seconds, 60):
                for existing_key, existing_events in list(self._events.items()):
                    while existing_events and now - existing_events[0] >= self.window_seconds:
                        existing_events.popleft()
                    if not existing_events:
                        del self._events[existing_key]
                self._last_prune = now

            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= self.requests:
                self._reject()
            events.append(now)

    def _reject(self) -> None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(self.window_seconds)},
        )

    def reset(self) -> None:
        """Test-only: clears the process-local fallback state. Does not
        touch Redis -- tests that need a clean Redis-backed slate clear the
        cuemix:ratelimit:* keys directly (see conftest.py's own upload-queue
        equivalent) rather than through this method."""

        with self._lock:
            self._events.clear()
            self._last_prune = monotonic()


auth_rate_limit = RateLimiter(requests=20, window_seconds=60)
write_rate_limit = RateLimiter(requests=60, window_seconds=60)
