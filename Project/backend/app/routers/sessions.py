"""Persistent public AI-DJ session routes used by the current frontend."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.user import User
from app.routers.auth import get_optional_current_user
from app.schemas import (
    PrepareNextRead,
    SessionFeedbackRequest,
    SessionRead,
    StartSessionRequest,
    StopSessionRead,
)
from app.services import session_manager
from app.services.pipeline.dependencies import (
    get_audio_renderer,
    get_catalog_candidate_retriever,
    get_segment_selector,
    get_session_candidate_retriever,
    get_transition_planner,
    get_vibe_understander,
)
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)
from app.services.pipeline.orchestrator import NoMatchingCandidate

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _existing(db: Session, session_id: str, current_user: User | None = None):
    session = session_manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    if session.user_id is not None and (
        current_user is None or session.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session belongs to another user.")
    return session


@router.post("/start", response_model=SessionRead)
def start_session(
    request: StartSessionRequest,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
    vibe: VibeUnderstander = Depends(get_vibe_understander),
    retriever: CandidateRetriever = Depends(get_session_candidate_retriever),
    fallback_retriever: CandidateRetriever = Depends(get_catalog_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    try:
        return session_manager.create_session(
            db,
            request.prompt,
            current_user.id if current_user else None,
            vibe=vibe,
            retriever=retriever,
            fallback_retriever=fallback_retriever,
            selector=selector,
            planner=planner,
            renderer=renderer,
        )
    except NoMatchingCandidate as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None


@router.get("/{session_id}", response_model=SessionRead)
def read_session(
    session_id: str,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    return session_manager.serialize_session(_existing(db, session_id, current_user))


@router.post("/{session_id}/feedback", response_model=SessionRead)
def send_feedback(
    session_id: str,
    request: SessionFeedbackRequest,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
    retriever: CandidateRetriever = Depends(get_session_candidate_retriever),
    fallback_retriever: CandidateRetriever = Depends(get_catalog_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    session = _existing(db, session_id, current_user)
    if session.status == "stopped":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already stopped.")
    return session_manager.apply_feedback(
        db,
        session,
        request.feedback,
        retriever=retriever,
        fallback_retriever=fallback_retriever,
        selector=selector,
        planner=planner,
        renderer=renderer,
    )


@router.post("/{session_id}/advance", response_model=SessionRead)
def advance_session(
    session_id: str,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
    retriever: CandidateRetriever = Depends(get_session_candidate_retriever),
    fallback_retriever: CandidateRetriever = Depends(get_catalog_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    """Called automatically by the frontend when the current track/segment
    finishes -- continues the session onto the next one matching its
    current intent, with no user input required. Explicit feedback
    (POST .../feedback) still redirects the session immediately; this only
    ever continues in the same direction."""

    session = _existing(db, session_id, current_user)
    if session.status == "stopped":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already stopped.")
    return session_manager.advance_session(
        db,
        session,
        retriever=retriever,
        fallback_retriever=fallback_retriever,
        selector=selector,
        planner=planner,
        renderer=renderer,
    )


@router.post("/{session_id}/prepare-next", response_model=PrepareNextRead)
def prepare_next(
    session_id: str,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
    retriever: CandidateRetriever = Depends(get_session_candidate_retriever),
    fallback_retriever: CandidateRetriever = Depends(get_catalog_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    """Best-effort prefetch of the session's next track/segment, ahead of
    when advance() actually needs it (PHASE_C_PREFETCH_DESIGN.md section
    3.2). Safe to call speculatively and repeatedly: a no-op, not an error,
    if the session isn't playing or a valid prepared item already exists."""

    session = _existing(db, session_id, current_user)
    session_manager.prepare_next(
        db,
        session,
        retriever=retriever,
        fallback_retriever=fallback_retriever,
        selector=selector,
        planner=planner,
        renderer=renderer,
    )
    prepared = session.prepared_next_json
    return PrepareNextRead(
        prepared=prepared is not None,
        audioUrl=prepared["now_playing"]["audio_url"] if prepared else None,
    )


@router.post("/{session_id}/stop", response_model=StopSessionRead)
def stop_session(
    session_id: str,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    return session_manager.stop_session(db, _existing(db, session_id, current_user))
