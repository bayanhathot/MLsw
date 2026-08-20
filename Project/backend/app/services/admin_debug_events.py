"""In-memory recent-activity feed for the owner-only admin debug dashboard
(routers/admin_debug.py).

Bounded, best-effort, process-local storage -- the ring buffer only ever
needs to answer "what happened recently," not act as a durable log. Durable
failure state already lives on the rows themselves (DJSession.
pipeline_trace_json, ExternalTrack.analysis_status/analysis_last_failed_at);
this is purely a live activity stream layered on top, matching the same
"REST/DB stays authoritative, WS/ring-buffer is a convenience" posture as
pipeline_debug_service.py and channel_hub.py.

record_event() is deliberately the same fire-and-forget, never-raise
posture as notify_pipeline_debug_change() and channel_hub.sync_publish(): a
missed or dropped event here must never affect the caller's own request or
background job. Every call site that records an event is one that was
already computing/logging this exact data for another reason (an existing
logger.info/logger.warning call, an existing notify_pipeline_debug_change()
call) -- this does not introduce any new instrumentation, only surfaces
what already gets computed.
"""

import logging
from collections import deque
from threading import Lock

from app.core.config import debug_dashboard_enabled
from app.services.channel_hub import sync_publish

logger = logging.getLogger(__name__)

_MAX_EVENTS = 200

_lock = Lock()
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)


def record_event(event: dict) -> None:
    """Append to the local ring buffer and best-effort publish to every
    connected admin-dashboard client over the "admin_debug" channel_hub
    channel. A no-op (no buffer growth, no Redis publish) when the
    dashboard itself is disabled, so a deployment that isn't using this
    feature pays no cost for it."""

    if not debug_dashboard_enabled():
        return
    try:
        with _lock:
            _events.append(event)
        sync_publish("admin_debug", "activity_event", event)
    except Exception:
        logger.debug("admin_debug_events: failed to record/publish event", exc_info=True)


def recent_events() -> list[dict]:
    """Most-recent-first snapshot for the dashboard's initial REST load."""

    with _lock:
        return list(reversed(_events))


def publish_session_updated(session_id: str) -> None:
    """Best-effort invalidation push for the dashboard's session list/detail
    view. Internally flag-gated (a no-op call site never has to check
    debug_dashboard_enabled() itself), mirroring
    pipeline_debug_service.notify_pipeline_debug_change()'s exact posture --
    called from the same sites, for the same reason, over the "admin_debug"
    channel_hub channel instead of the process-local pipeline_debug_hub."""

    if not debug_dashboard_enabled():
        return
    try:
        sync_publish("admin_debug", "session_updated", {"session_id": session_id})
    except Exception:
        logger.debug("admin_debug_events: failed to publish session_updated", exc_info=True)


def publish_external_track_updated(external_track_id: int) -> None:
    """Best-effort invalidation push for the dashboard's Audius-cache table
    view. Same posture as publish_session_updated above."""

    if not debug_dashboard_enabled():
        return
    try:
        sync_publish(
            "admin_debug", "external_track_updated", {"external_track_id": external_track_id}
        )
    except Exception:
        logger.debug("admin_debug_events: failed to publish external_track_updated", exc_info=True)
