"""
play_events.py

Route for reporting real listening time (see PostCard.svelte's
heartbeat + pause/segment-advance/unmount flush points).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import PlayEventCreate, PlayEventRead
from app.services import play_event_service

router = APIRouter(prefix="/play-events", tags=["play-events"])


@router.post("", response_model=PlayEventRead, status_code=status.HTTP_201_CREATED)
def create_play_event(
    event_data: PlayEventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = play_event_service.record_play_event(
        db=db,
        user_id=current_user.id,
        mix_id=event_data.mix_id,
        segment_id=event_data.segment_id,
        seconds_listened=event_data.seconds_listened,
        event_type=event_data.event_type,
        post_id=event_data.post_id,
    )

    return PlayEventRead(id=event.id, seconds_listened=event.seconds_listened)
