"""Authenticated raw listening-event ingestion."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import ListeningEventCreate, ListeningEventRead
from app.services import listening_service

router = APIRouter(prefix="/listening-events", tags=["listening"])


@router.post("", response_model=ListeningEventRead, status_code=status.HTTP_201_CREATED)
def record_listening_event(
    request: ListeningEventCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return listening_service.create_event(db, request, current_user.id)
