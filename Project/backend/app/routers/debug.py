"""Internal AI-DJ pipeline and Ollama observability.

Gated behind ENABLE_PIPELINE_DEBUG (app.core.config.pipeline_debug_enabled,
off by default -- the same explicit-opt-in shape as ALLOW_DEMO_SEED in
app/seed.py) *and* a logged-in user (auth.get_current_user), rather than
inventing a new access-control mechanism for one internal page. Read-only:
nothing here can trigger or change pipeline behavior, only reflect state the
session/pipeline layer already produced.
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import cors_origins, pipeline_debug_enabled
from app.core.security import decode_access_token
from app.database.database import get_db
from app.database.models.session import DJSession
from app.database.models.user import User
from app.routers.auth import ACCESS_TOKEN_COOKIE_NAME, get_current_user
from app.schemas import OllamaHealthRead, PipelineDebugRead, SessionPipelineDebugRead
from app.services.pipeline.ollama_health import check_ollama_health
from app.services.pipeline_debug_service import pipeline_debug_hub
from app.services.prompt_parser import get_last_ollama_call

router = APIRouter(prefix="/debug", tags=["debug"])

# Enough to see recent activity across users without an unbounded query;
# this is a live-observability view, not a paginated archive.
_RECENT_SESSION_LIMIT = 20


def _require_enabled() -> None:
    """404s rather than 403s when disabled, so the panel's existence isn't
    revealed to a normal visitor even by probing the endpoint."""

    if not pipeline_debug_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _ollama_section() -> OllamaHealthRead:
    health = check_ollama_health()
    health["last_call"] = get_last_ollama_call()
    return OllamaHealthRead.model_validate(health)


@router.get("/pipeline", response_model=PipelineDebugRead)
def read_pipeline_debug(
    _enabled: None = Depends(_require_enabled),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(DJSession)
        .order_by(desc(DJSession.updated_at))
        .limit(_RECENT_SESSION_LIMIT)
        .all()
    )
    return PipelineDebugRead(
        ollama=_ollama_section(),
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
            )
            for session in sessions
        ],
    )


@router.websocket("/ws")
async def pipeline_debug_socket(websocket: WebSocket, db: Session = Depends(get_db)):
    """Invalidation-only push, same shape as /posts/ws/community: a client
    reconnecting here re-fetches GET /debug/pipeline rather than trusting
    anything pushed over the socket."""

    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin and origin not in cors_origins():
        await websocket.close(code=4403)
        return
    if not pipeline_debug_enabled():
        await websocket.close(code=4404)
        return

    token = websocket.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    subject = decode_access_token(token) if token else None
    try:
        user_id = int(subject) if subject is not None else None
    except ValueError:
        user_id = None
    if user_id is None:
        await websocket.close(code=4401)
        return
    user = db.query(User).filter_by(id=user_id, is_active=True).first()
    if user is None:
        await websocket.close(code=4401)
        return

    await pipeline_debug_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pipeline_debug_hub.disconnect(websocket)
