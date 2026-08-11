"""In-process WebSocket fanout backed by durable notification rows.

For multiple API processes, replace this fanout layer with Redis pub/sub; the
database notification remains durable regardless of process topology.
"""

from collections import defaultdict

from fastapi import WebSocket


class NotificationHub:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        self.connections[user_id].discard(websocket)
        if not self.connections[user_id]:
            self.connections.pop(user_id, None)

    async def publish(self, user_id: int, payload: dict) -> None:
        stale = []
        for websocket in tuple(self.connections.get(user_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(user_id, websocket)


notification_hub = NotificationHub()
