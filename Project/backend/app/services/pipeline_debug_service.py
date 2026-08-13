"""Process-local realtime invalidation for the internal pipeline debug panel.

Mirrors community_service.CommunityHub exactly: the broadcast payload carries
no trace data, only an invalidation signal, so a client always re-fetches the
current state through the authorized, flag-gated REST endpoint
(routers/debug.py) rather than trusting anything pushed over the socket. A
future multi-worker deployment can replace this hub with Redis pub/sub
without changing either API, same as the other hubs.
"""

import logging

import anyio
from fastapi import WebSocket

from app.core.config import pipeline_debug_enabled

logger = logging.getLogger(__name__)


class PipelineDebugHub:
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
                await websocket.send_json({"type": "pipeline_trace_updated"})
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


pipeline_debug_hub = PipelineDebugHub()


def notify_pipeline_debug_change() -> None:
    """Sync-safe trigger for the hub broadcast, callable from session_manager
    (which runs synchronously in FastAPI's threadpool, not an async context).

    Best-effort only, matching the other hubs' "REST remains authoritative"
    posture: a missed push (feature disabled, no listeners, or this call
    happening outside a request's worker thread, e.g. in a unit test) must
    never affect the actual session flow.
    """

    if not pipeline_debug_enabled():
        return
    try:
        anyio.from_thread.run(pipeline_debug_hub.publish_change)
    except Exception:
        logger.debug("Skipped live pipeline-debug push (no active WS listeners or worker-thread context).")
