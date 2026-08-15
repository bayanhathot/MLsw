"""Coverage for the Redis reachability probe (app.core.redis_client),
mirroring services/pipeline/ollama_health.py's own tests: unconfigured,
reachable, and unreachable all degrade gracefully without raising."""

import pytest
import redis.asyncio as redis

from app.core.redis_client import check_redis_health


@pytest.mark.anyio
async def test_redis_health_reports_unconfigured_without_a_connection_attempt(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    def unexpected_call(*args, **kwargs):
        raise AssertionError("check_redis_health must not connect with no REDIS_URL configured")

    monkeypatch.setattr(redis.Redis, "ping", unexpected_call)
    health = await check_redis_health()
    assert health == {
        "configured": False,
        "reachable": False,
        "error": "REDIS_URL is not set.",
    }


@pytest.mark.anyio
async def test_redis_health_reports_reachable_on_a_successful_ping(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis.invalid:6379/0")

    async def fake_ping(self, *args, **kwargs):
        return True

    monkeypatch.setattr(redis.Redis, "ping", fake_ping)
    health = await check_redis_health()
    assert health == {
        "configured": True,
        "reachable": True,
        "error": None,
    }


@pytest.mark.anyio
async def test_redis_health_degrades_to_unreachable_on_connection_error(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis.invalid:6379/0")

    async def fake_ping(self, *args, **kwargs):
        raise redis.ConnectionError("Connection refused")

    monkeypatch.setattr(redis.Redis, "ping", fake_ping)
    health = await check_redis_health()
    assert health["configured"] is True
    assert health["reachable"] is False
    assert health["error"]


@pytest.mark.anyio
async def test_redis_health_degrades_to_unreachable_on_timeout(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis.invalid:6379/0")

    async def hang_forever(self, *args, **kwargs):
        import asyncio

        await asyncio.sleep(10)

    monkeypatch.setattr(redis.Redis, "ping", hang_forever)
    monkeypatch.setattr("app.core.redis_client._HEALTH_TIMEOUT_SECONDS", 0.05)
    health = await check_redis_health()
    assert health["configured"] is True
    assert health["reachable"] is False
    assert health["error"]
