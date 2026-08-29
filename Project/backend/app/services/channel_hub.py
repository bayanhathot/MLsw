"""ChannelHub: multi-channel WebSocket fanout backed by Redis pub/sub.

The sole real-time system for forum/messaging/social/mixes events. Every
connection is auto-subscribed to "user:{their_id}" on connect, plus zero or
more explicit channels ("post:42", "feed:discussions",
"conversation:7:19") added via .subscribe(). Conversation channels contain
both participant ids in ascending order so they cannot be mistaken for every
conversation involving one user.

Redis is the single source of truth for delivery, even within one process:
publish() only writes to one fixed Redis channel; a single background task
per worker subscribes to it once and fans each event out to this process's
local connections, filtered by the event's own "channel" field. This keeps
single-process and multi-process behavior identical, and it degrades to
publish() being a no-op (fail-open, never raises) when Redis is unconfigured
or unreachable -- the same posture as redis_client.py.
"""

import asyncio
import json
import logging

from fastapi import WebSocket

from app.core.redis_client import get_redis_client, get_sync_redis_client

logger = logging.getLogger("cuemix.channel_hub")

_REDIS_CHANNEL = "cuemix:channel_hub"
# See stop_listener()'s own comment: bounds how long app shutdown will ever
# wait on the listener task's cleanup before giving up on it.
_LISTENER_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def conversation_channel(user_id: int, other_id: int) -> str:
    """Return the one canonical channel shared by exactly two users."""

    first, second = sorted((user_id, other_id))
    if first <= 0 or first == second:
        raise ValueError("A conversation needs two distinct positive user ids.")
    return f"conversation:{first}:{second}"


def conversation_participants(channel: str) -> tuple[int, int] | None:
    """Parse a canonical conversation channel, rejecting legacy/forged names."""

    parts = channel.split(":")
    if len(parts) != 3 or parts[0] != "conversation":
        return None
    try:
        first, second = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if first <= 0 or first >= second:
        return None
    return first, second


def sync_publish(channel: str, event_type: str, data: dict) -> None:
    """The synchronous counterpart to ChannelHub.publish(), for callers that
    aren't running inside an asyncio event loop -- upload_queue.py's worker
    threads pushing live batch/job status and upload notifications,
    specifically. Publishes onto the exact same Redis channel, so this
    process's own async _listen() loop (and every other process's) delivers
    it to matching local WebSocket subscribers exactly as if `await
    channel_hub.publish(...)` had been called -- Redis pub/sub is what
    actually decouples this from needing the event loop at all. Fails open,
    same posture as publish()."""

    client = get_sync_redis_client()
    if client is None:
        return
    envelope = {"channel": channel, "type": event_type, "data": data}
    try:
        client.publish(_REDIS_CHANNEL, json.dumps(envelope))
    except Exception:
        logger.warning("channel_hub sync_publish failed", exc_info=True)


class ChannelHub:
    def __init__(self) -> None:
        self._subscriptions: dict[WebSocket, set[str]] = {}
        # Keyed by event loop rather than a single task: production only ever
        # runs one loop per process (BACKEND_WORKERS=1), but the test suite
        # instantiates multiple TestClient(app)s against this same singleton,
        # each driving the ASGI lifespan on its own independent loop. A single
        # shared task attribute would have one loop's stop_listener() awaiting
        # (or cancelling) a task that belongs to a different, unrelated loop.
        self._listener_tasks: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._subscriptions[websocket] = {f"user:{user_id}"}

    def disconnect(self, websocket: WebSocket) -> None:
        self._subscriptions.pop(websocket, None)

    def subscribe(self, websocket: WebSocket, channel: str) -> None:
        self._subscriptions.setdefault(websocket, set()).add(channel)

    def unsubscribe(self, websocket: WebSocket, channel: str) -> None:
        self._subscriptions.get(websocket, set()).discard(channel)

    async def publish(self, channel: str, event_type: str, data: dict) -> None:
        """Fan an event out to every connection subscribed to `channel`, on
        this process and every other one, via Redis. Fails open: an
        unreachable/unconfigured Redis silently drops the event instead of
        raising, matching redis_client.py's posture."""

        client = get_redis_client()
        if client is None:
            return
        envelope = {"channel": channel, "type": event_type, "data": data}
        try:
            await client.publish(_REDIS_CHANNEL, json.dumps(envelope))
        except Exception:
            logger.warning("channel_hub publish failed", exc_info=True)

    async def deliver_local(self, envelope: dict) -> None:
        """Send an already-decoded envelope to this process's matching
        local subscribers. Split out from the Redis listener loop so it can
        be exercised directly in tests without a real (or fake) Redis."""

        channel = envelope.get("channel")
        stale = []
        for websocket, channels in tuple(self._subscriptions.items()):
            if channel in channels:
                try:
                    await websocket.send_json(envelope)
                except Exception:
                    stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)

    async def start_listener(self) -> None:
        """Idempotent per event loop: safe to call on every app startup. No-ops
        when Redis isn't configured, same fail-open posture as publish()."""

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
            # Bounded, not just cancel()-and-await: a cancelled task's own
            # cleanup (pubsub.close(), specifically) can still hang past the
            # cancellation if the underlying socket has a pending OS-level
            # read that never completes -- observed in practice on Windows,
            # where the ProactorEventLoop won't finish closing until that
            # settles, wedging the whole app lifespan shutdown (and, in
            # tests, every fixture torn down after it) indefinitely. This
            # timeout is what makes shutdown itself fail open the same way
            # every other Redis touchpoint here already does.
            await asyncio.wait_for(task, timeout=_LISTENER_SHUTDOWN_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning("channel_hub listener did not stop within %ss; abandoning it", _LISTENER_SHUTDOWN_TIMEOUT_SECONDS)

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
                logger.warning("channel_hub listener error, retrying", exc_info=True)
                await asyncio.sleep(1)
            finally:
                # Bounded for the same reason stop_listener() bounds its own
                # wait: pubsub.close() can hang past a CancelledError if the
                # underlying socket has a pending OS-level read that never
                # completes, which is the actual operation observed stuck on
                # Windows -- cancelling *this* coroutine doesn't reach down
                # into that. asyncio.CancelledError is deliberately excluded
                # from the catch-all here (unlike stop_listener's own except)
                # so a real cancellation still propagates and this loop
                # actually exits, rather than swallowing it and looping
                # again after the caller thinks it already stopped.
                try:
                    await asyncio.wait_for(
                        asyncio.shield(pubsub.close()), timeout=_LISTENER_SHUTDOWN_TIMEOUT_SECONDS
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass


channel_hub = ChannelHub()
