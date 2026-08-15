"""ChannelHub: multi-channel WebSocket fanout backed by Redis pub/sub.

The sole real-time system for forum/messaging/social/mixes events. Every
connection is auto-subscribed to "user:{their_id}" on connect, plus zero or
more explicit channels ("post:42", "feed:discussions", "conversation:7")
added via .subscribe().

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

from app.core.redis_client import get_redis_client

logger = logging.getLogger("cuemix.channel_hub")

_REDIS_CHANNEL = "cuemix:channel_hub"


class ChannelHub:
    def __init__(self) -> None:
        self._subscriptions: dict[WebSocket, set[str]] = {}
        self._listener_task: asyncio.Task | None = None

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
        """Idempotent: safe to call on every app startup. No-ops when Redis
        isn't configured, same fail-open posture as publish()."""

        if self._listener_task is not None:
            return
        client = get_redis_client()
        if client is None:
            return
        self._listener_task = asyncio.create_task(self._listen(client))

    async def stop_listener(self) -> None:
        task, self._listener_task = self._listener_task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

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
                try:
                    await pubsub.close()
                except Exception:
                    pass


channel_hub = ChannelHub()
