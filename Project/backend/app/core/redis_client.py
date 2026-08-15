"""Shared async Redis client and reachability probe.

Purely additive infrastructure -- nothing else in the app depends on Redis
yet. Lazy-connected and fail-open, the same posture as
services/pipeline/ollama_health.py: a missing/unreachable REDIS_URL never
raises at import time or from the health check, it only shows up as
"reachable": False.
"""

import asyncio
import os

import redis.asyncio as redis

_HEALTH_TIMEOUT_SECONDS = 2.0

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis | None:
    """Return the shared, lazily-created Redis client.

    Returns None when REDIS_URL is not configured -- callers should treat
    that the same as an unreachable Redis rather than special-casing it.
    """

    global _client
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    if _client is None:
        _client = redis.from_url(redis_url, decode_responses=True)
    return _client


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
