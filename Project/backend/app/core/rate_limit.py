"""Small dependency-free sliding-window limiter for abuse-prone endpoints.

This protects a single process.  Multi-replica production deployments should
replace the storage with Redis while keeping the same dependency interface.
"""

from collections import deque
import os
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
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
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                    headers={"Retry-After": str(self.window_seconds)},
                )
            events.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._last_prune = monotonic()


auth_rate_limit = RateLimiter(requests=20, window_seconds=60)
write_rate_limit = RateLimiter(requests=60, window_seconds=60)
