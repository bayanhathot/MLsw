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
from app.services.admin_debug_events import record_event
from app.services.pipeline.dependencies import (
    get_audio_renderer,
    get_audius_candidate_retriever,
    get_full_track_segment_selector,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found."
        )
    if session.user_id is not None and (
        current_user is None or session.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user.",
        )
    return session


def _selector_for(
    mix_scope: str, selector: SegmentSelector, full_track_selector: SegmentSelector
) -> SegmentSelector:
    """The one place mix_scope picks a SegmentSelector -- 'full_songs' is
    the only value that ever diverges from today's default. See
    DJSession.mix_scope's own docstring for why this is decided per-call
    from a persisted session field (or, at creation, the request itself)
    rather than threaded through session_manager.py's own signatures."""

    return full_track_selector if mix_scope == "full_songs" else selector


@router.post("/start", response_model=SessionRead)
def start_session(
    request: StartSessionRequest,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
    vibe: VibeUnderstander = Depends(get_vibe_understander),
    retriever: CandidateRetriever = Depends(get_session_candidate_retriever),
    fallback_retriever: CandidateRetriever = Depends(get_audius_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    full_track_selector: SegmentSelector = Depends(get_full_track_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    try:
        return session_manager.create_session(
            db,
            request.prompt,
            current_user.id if current_user else None,
            mode=request.mode,
            mix_scope=request.mix_scope,
            vibe=vibe,
            retriever=retriever,
            fallback_retriever=fallback_retriever,
            selector=_selector_for(request.mix_scope, selector, full_track_selector),
            planner=planner,
            renderer=renderer,
        )
    except NoMatchingCandidate as exc:
        # The one true "nothing was ever created" case -- every other
        # NoMatchingCandidate site is mid-session (session_manager.py),
        # where the existing session/trace already stays queryable and
        # doesn't need a separate failure record.
        record_event(
            {
                "event": "session_create_failed",
                "prompt": request.prompt,
                "reason": str(exc),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None


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
    fallback_retriever: CandidateRetriever = Depends(get_audius_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    full_track_selector: SegmentSelector = Depends(get_full_track_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    session = _existing(db, session_id, current_user)
    if session.status == "stopped":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Session is already stopped."
        )
    return session_manager.apply_feedback(
        db,
        session,
        request.feedback,
        retriever=retriever,
        fallback_retriever=fallback_retriever,
        selector=_selector_for(session.mix_scope, selector, full_track_selector),
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
    fallback_retriever: CandidateRetriever = Depends(get_audius_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    full_track_selector: SegmentSelector = Depends(get_full_track_segment_selector),
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Session is already stopped."
        )
    return session_manager.advance_session(
        db,
        session,
        retriever=retriever,
        fallback_retriever=fallback_retriever,
        selector=_selector_for(session.mix_scope, selector, full_track_selector),
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
    fallback_retriever: CandidateRetriever = Depends(get_audius_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    full_track_selector: SegmentSelector = Depends(get_full_track_segment_selector),
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
        selector=_selector_for(session.mix_scope, selector, full_track_selector),
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
