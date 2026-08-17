"""Shared Redis clients (async + sync) and a reachability probe.

Redis now has a real job (upload_queue.py's durable job/batch store, see its
own module docstring) alongside its original purely-additive role here --
still lazy-connected and fail-open, the same posture as
services/pipeline/ollama_health.py: a missing/unreachable REDIS_URL never
raises at import time or from the health check, only shows up as
"reachable": False (upload_queue.py falls back to its original in-memory-
only behavior in that case, rather than crashing the app).
"""

import asyncio
import os

import redis as sync_redis
import redis.asyncio as redis

_HEALTH_TIMEOUT_SECONDS = 2.0
# Neither redis-py client sets a socket timeout by default, which means a
# connection that goes silently dead (no clean FIN/RST -- observed in
# practice against a Dockerized Redis on this stack) blocks a caller
# *forever* on the next read/write, not just until the next request fails.
# For upload_queue.py's worker threads specifically, that turns into a wedged
# worker holding UploadQueue._submission_lock indefinitely, which then blocks
# every subsequent submit() too -- a total outage caused by the one dependency
# this whole module's docstring promises is purely additive. A bounded
# timeout restores the fail-open contract: a hung connection now surfaces as
# a normal, catchable redis.RedisError within a few seconds instead of a
# silent deadlock.
_SOCKET_TIMEOUT_SECONDS = 5.0

_client: redis.Redis | None = None
_sync_client: sync_redis.Redis | None = None


def get_redis_client() -> redis.Redis | None:
    """Return the shared, lazily-created async Redis client.

    Returns None when REDIS_URL is not configured -- callers should treat
    that the same as an unreachable Redis rather than special-casing it.
    """

    global _client
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    if _client is None:
        _client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
    return _client


def get_sync_redis_client() -> sync_redis.Redis | None:
    """The synchronous counterpart to get_redis_client(), for callers that
    aren't running inside an asyncio event loop -- upload_queue.py's worker
    threads, specifically. Same lazy-connect/None-when-unconfigured
    contract; points at the same Redis instance/URL, just a different
    client object since the sync and async redis-py clients aren't
    interchangeable."""

    global _sync_client
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    if _sync_client is None:
        _sync_client = sync_redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
    return _sync_client


async def check_redis_health() -> dict:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return {
            "configured": False,
            "reachable": False,
            "error": "REDIS_URL is not set.",
        }

    client = get_redis_client()
    try:
        await asyncio.wait_for(client.ping(), timeout=_HEALTH_TIMEOUT_SECONDS)
    except (redis.RedisError, OSError, asyncio.TimeoutError) as exc:
        return {
            "configured": True,
            "reachable": False,
            "error": str(exc) or exc.__class__.__name__,
        }

    return {
        "configured": True,
        "reachable": True,
        "error": None,
    }
