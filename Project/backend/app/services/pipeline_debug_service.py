"""Realtime invalidation for the internal pipeline debug panel, backed by
Redis pub/sub -- same architecture as channel_hub.py (see that module's own
docstring), ported for D6b so a change on one BACKEND_WORKERS replica
correctly pushes to a client connected to a *different* replica, not only
to whichever process happened to handle the session request that triggered
it. Fails open exactly like channel_hub.py: an unreachable/unconfigured
Redis silently drops the push instead of raising or blocking the session
request that triggered it -- the broadcast payload carries no trace data,
only an invalidation signal, so a client always re-fetches the current
state through the authorized, flag-gated REST endpoint (routers/debug.py)
rather than trusting anything pushed over the socket; losing a push just
means the client's next manual refresh (or reconnect) is what shows the
change instead of a live update.
"""

import asyncio
import json
import logging

from fastapi import WebSocket

from app.core.config import pipeline_debug_enabled
from app.core.redis_client import get_redis_client, get_sync_redis_client

logger = logging.getLogger(__name__)

_REDIS_CHANNEL = "cuemix:pipeline_debug"
# See stop_listener()'s own comment: bounds how long app shutdown will ever
# wait on the listener task's cleanup before giving up on it.
_LISTENER_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class PipelineDebugHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        # Keyed by event loop, not a single task -- see channel_hub.py's
        # identical _listener_tasks comment for why (multiple TestClient(app)
        # instances in the test suite, each its own loop, against this same
        # module-level singleton).
        self._listener_tasks: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def publish_change(self) -> None:
        """Fan the invalidation signal out to every connection, on this
        process and every other one, via Redis. Fails open: an unreachable/
        unconfigured Redis silently drops the event instead of raising,
        matching redis_client.py's posture."""

        client = get_redis_client()
        if client is None:
            return
        try:
            await client.publish(_REDIS_CHANNEL, json.dumps({"type": "pipeline_trace_updated"}))
        except Exception:
            logger.warning("pipeline_debug_hub publish failed", exc_info=True)

    async def deliver_local(self, envelope: dict) -> None:
        """Send an already-decoded envelope to this process's own local
        connections. Split out from the Redis listener loop so it can be
        exercised directly in tests without a real (or fake) Redis."""

        stale: list[WebSocket] = []
        for websocket in tuple(self._connections):
            try:
                await websocket.send_json(envelope)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)

    async def start_listener(self) -> None:
        """Idempotent per event loop: safe to call on every app startup. No-ops
        when Redis isn't configured, same fail-open posture as publish_change()."""

        loop = asyncio.get_running_loop()
        if loop in self._listener_tasks:
            return
        client = get_redis_client()
        if client is None:
            return
        self._listener_tasks[loop] = asyncio.create_task(self._listen(client))

    async def stop_listener(self) -> None:
        task = self._listener_tasks.pop(asyncio.get_running_loop(), None)
        if task is None:
            return
        task.cancel()
        try:
            # Bounded, not just cancel()-and-await -- see channel_hub.py's
            # identical stop_listener() comment for the observed Windows
            # ProactorEventLoop hang this guards against.
            await asyncio.wait_for(task, timeout=_LISTENER_SHUTDOWN_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning(
                "pipeline_debug_hub listener did not stop within %ss; abandoning it",
                _LISTENER_SHUTDOWN_TIMEOUT_SECONDS,
            )

    async def _listen(self, client) -> None:
        while True:
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(_REDIS_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(message["data"])
                    except (TypeError, ValueError):
                        continue
                    await self.deliver_local(envelope)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("pipeline_debug_hub listener error, retrying", exc_info=True)
                await asyncio.sleep(1)
            finally:
                # Bounded for the same reason stop_listener() bounds its own
                # wait -- see channel_hub.py's identical _listen() comment.
                try:
                    await asyncio.wait_for(
                        asyncio.shield(pubsub.close()), timeout=_LISTENER_SHUTDOWN_TIMEOUT_SECONDS
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass


pipeline_debug_hub = PipelineDebugHub()


def notify_pipeline_debug_change() -> None:
    """Sync-safe trigger for the hub broadcast, callable from session_manager
    (which runs synchronously in FastAPI's threadpool, not an async context).

    Publishes onto Redis directly via the sync client -- mirrors
    channel_hub.sync_publish exactly (including its fail-open try/except),
    rather than the old anyio.from_thread.run(...) bridge this replaced: that
    bridge only ever reached this same process's own in-memory connections
    anyway, and needed an active event loop backing the calling thread to
    work at all (fragile outside a real request's worker thread, e.g. a unit
    test). A direct Redis publish has neither limitation."""

    if not pipeline_debug_enabled():
        return
    client = get_sync_redis_client()
    if client is None:
        return
    try:
        client.publish(_REDIS_CHANNEL, json.dumps({"type": "pipeline_trace_updated"}))
    except Exception:
        logger.warning("pipeline_debug_hub sync publish failed", exc_info=True)
