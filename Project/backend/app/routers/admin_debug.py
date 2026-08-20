"""Owner-only admin debug dashboard: session-loop visibility, the Audius
persistent-analysis cache, and a recent-activity/failure feed.

Distinct from routers/debug.py (the internal AI-DJ pipeline/Ollama panel,
deliberately unauthenticated -- see that module's own docstring for why):
this route carries strictly more sensitive surface (every user's session
prompts plus a raw external_tracks table), so it requires both an
authenticated session AND that the authenticated user's ID matches
DEBUG_DASHBOARD_OWNER_USER_ID, tied to one specific account rather than a
new role/permission system (see app.core.config.debug_dashboard_owner_user_id).

Every failure mode -- flag off, not logged in, logged in as someone else --
returns a plain 404, never 401/403, so the route's existence isn't
confirmed to an unauthorized requester (see _require_owner below).

Read-only: nothing here can trigger or change pipeline behavior, only
reflect state the session/analysis layers already produced and persisted
(DJSession.pipeline_trace_json, ExternalTrack rows, the admin_debug_events
ring buffer). See services/admin_debug_events.py's own docstring for why
none of this introduces new instrumentation.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.core.config import debug_dashboard_enabled, debug_dashboard_owner_user_id
from app.database.database import get_db
from app.database.models.external_track import ExternalTrack
from app.database.models.session import DJSession
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import (
    AdminDebugEventsRead,
    AdminDebugExternalTracksRead,
    AdminDebugSessionsRead,
    ExternalTrackDebugRead,
    SessionPipelineDebugRead,
)
from app.services.admin_debug_events import recent_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/debug", tags=["admin_debug"])

# Same reasoning as routers/debug.py's own _RECENT_SESSION_LIMIT: enough to
# see recent activity without an unbounded query.
_RECENT_SESSION_LIMIT = 50
_RECENT_EXTERNAL_TRACK_LIMIT = 200


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _require_owner(request: Request, db: Session = Depends(get_db)) -> User:
    """404s -- never 401/403 -- for every failure mode, so a normal visitor
    (or a signed-in but unauthorized user) sees no evidence this route
    exists at all, matching routers/debug.py's own _require_enabled
    precedent for the exact same reason.

    Checks the flag first (cheap, no DB hit) before even attempting auth."""

    if not debug_dashboard_enabled():
        raise _not_found()
    owner_id = debug_dashboard_owner_user_id()
    if owner_id is None:
        raise _not_found()
    try:
        current_user = get_current_user(request=request, db=db)
    except HTTPException:
        raise _not_found() from None
    if current_user.id != owner_id:
        raise _not_found()
    return current_user


@router.get("/sessions", response_model=AdminDebugSessionsRead)
def read_sessions(
    _owner: User = Depends(_require_owner),
    db: Session = Depends(get_db),
):
    """Most recent sessions first, full pipeline_trace per session --
    reuses the exact same schema/shape routers/debug.py's own
    read_pipeline_debug already serves (Prompt 16's instrumentation, not
    duplicated here), just with a longer window and owner-only access
    instead of ENABLE_PIPELINE_DEBUG's no-login posture."""

    sessions = (
        db.query(DJSession)
        .order_by(desc(DJSession.updated_at))
        .limit(_RECENT_SESSION_LIMIT)
        .all()
    )
    return AdminDebugSessionsRead(
        sessions=[
            SessionPipelineDebugRead(
                session_id=session.id,
                prompt=session.prompt,
                status=session.status,
                user_id=session.user_id,
                retriever_name=session.retriever_name,
                vibe_label=session.vibe_label,
                updated_at=session.updated_at,
                trace=session.pipeline_trace_json,
                has_prepared_next=session.prepared_next_json is not None,
            )
            for session in sessions
        ]
    )


@router.get("/external-tracks", response_model=AdminDebugExternalTracksRead)
def read_external_tracks(
    search: str | None = None,
    _owner: User = Depends(_require_owner),
    db: Session = Depends(get_db),
):
    """Read-only external_tracks table view, most recently seen first.
    `search` matches artist or title (case-insensitive substring) so a
    specific track (e.g. one just played) can be found quickly -- see
    ExternalTrackDebugRead's own docstring for which columns are
    deliberately excluded."""

    query = db.query(ExternalTrack)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(ExternalTrack.artist.ilike(pattern), ExternalTrack.title.ilike(pattern)))
    rows = query.order_by(desc(ExternalTrack.last_seen_at)).limit(_RECENT_EXTERNAL_TRACK_LIMIT).all()
    return AdminDebugExternalTracksRead(
        tracks=[ExternalTrackDebugRead.model_validate(row) for row in rows]
    )


@router.get("/events", response_model=AdminDebugEventsRead)
def read_events(_owner: User = Depends(_require_owner)):
    """Recent structured latency/deadline/failure events (most recent
    first) from the in-memory ring buffer -- a live activity/failure feed,
    not a full log viewer; see services/admin_debug_events.py's own
    docstring. Link to real backend logs for anything needing more context
    than these structured summaries carry."""

    return AdminDebugEventsRead(events=recent_events())
