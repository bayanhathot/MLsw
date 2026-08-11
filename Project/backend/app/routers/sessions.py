"""Persistent public AI-DJ session routes used by the current frontend."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.user import User
from app.routers.auth import get_optional_current_user
from app.schemas import SessionFeedbackRequest, SessionRead, StartSessionRequest, StopSessionRead
from app.services import session_manager

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
):
    return session_manager.create_session(db, request.prompt, current_user.id if current_user else None)


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
):
    session = _existing(db, session_id, current_user)
    if session.status == "stopped":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already stopped.")
    return session_manager.apply_feedback(db, session, request.feedback)


@router.post("/{session_id}/stop", response_model=StopSessionRead)
def stop_session(
    session_id: str,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    return session_manager.stop_session(db, _existing(db, session_id, current_user))
