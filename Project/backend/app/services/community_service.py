"""Process-local realtime invalidation for the Community feed.

The payload intentionally contains no private post data. Clients simply re-fetch
through the authorized REST feed when something changes. A future multi-worker
deployment can replace this hub with Redis pub/sub without changing the API.
"""

from fastapi import WebSocket


class CommunityHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def publish_change(self) -> None:
        stale: list[WebSocket] = []
        for websocket in tuple(self._connections):
            try:
                await websocket.send_json({"type": "feed_changed"})
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


community_hub = CommunityHub()
