"""
play_event_service.py

Business logic for recording real listening time.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models.mix import MixSegment
from app.database.models.play_event import PlayEvent

# A single event should never exceed roughly the heartbeat interval
# (~15s) plus a small buffer - this is a cheap defense against one
# client sending an inflated event to fake minutes_listened. The
# PlayEventCreate schema already caps the field at 60 for basic input
# validation; this is the real, tighter clamp actually applied.
MAX_SECONDS_PER_EVENT = 25


def record_play_event(
    db: Session,
    user_id: int,
    mix_id: int,
    segment_id: int,
    seconds_listened: int,
    event_type: str,
    post_id: int | None = None,
) -> PlayEvent:
    segment = (
        db.query(MixSegment)
        .filter(MixSegment.id == segment_id, MixSegment.mix_id == mix_id)
        .first()
    )

    if segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found for this mix.",
        )

    event = PlayEvent(
        user_id=user_id,
        mix_id=mix_id,
        segment_id=segment_id,
        post_id=post_id,
        seconds_listened=min(seconds_listened, MAX_SECONDS_PER_EVENT),
        client_event_type=event_type,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return event
