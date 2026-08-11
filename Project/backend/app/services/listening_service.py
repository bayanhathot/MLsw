"""Create trustworthy raw listening events from known Zonix playback contexts."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.mix import Mix, MixSegment
from app.database.models.music_identity import ListeningEvent
from app.database.models.session import DJSession
from app.schemas import ListeningEventCreate
from app.services.session_manager import TRACKS

# Tolerate ordinary clock skew between the client and server; anything beyond
# this is treated as an impossible/future timestamp that could corrupt
# Music Identity analytics rather than reflect real playback.
_FUTURE_TOLERANCE = timedelta(minutes=5)


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _reject_future_timestamp(value: datetime | None, *, field_name: str) -> None:
    if value is None:
        return
    if value > utc_now() + _FUTURE_TOLERANCE:
        raise HTTPException(status_code=422, detail=f"{field_name} cannot be in the future.")


def _existing_event(db: Session, client_event_id: str, user_id: int) -> ListeningEvent | None:
    event = (
        db.query(ListeningEvent)
        .filter(ListeningEvent.client_event_id == client_event_id)
        .first()
    )
    if event is None:
        return None
    if event.user_id != user_id:
        raise HTTPException(status_code=409, detail="Listening event identifier already exists.")
    return event


def _mix_context(db: Session, request: ListeningEventCreate, user_id: int) -> dict:
    if request.mix_id is None or request.segment_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mix listening events require both mix_id and segment_id.",
        )
    mix = db.query(Mix).filter(Mix.id == request.mix_id).first()
    if mix is None:
        raise HTTPException(status_code=404, detail="Mix not found.")
    if mix.status != "published" and mix.owner_id != user_id:
        raise HTTPException(status_code=403, detail="This mix is not available to this user.")
    segment = (
        db.query(MixSegment)
        .filter(MixSegment.id == request.segment_id, MixSegment.mix_id == mix.id)
        .first()
    )
    if segment is None:
        raise HTTPException(status_code=422, detail="Segment does not belong to this mix.")
    segment_length = max(1, segment.end_second - segment.start_second)
    return {
        "session_id": None,
        "mix_id": mix.id,
        "segment_id": segment.id,
        "source": segment.source,
        "source_track_id": segment.source_track_id,
        "track_title": segment.title,
        "artist_name": segment.artist,
        "genre": segment.genre,
        "vibe": segment.vibe,
        "track_duration_seconds": max(segment.end_second, segment_length),
        "segment_start_second": segment.start_second,
        "segment_end_second": segment.end_second,
        "expected_seconds": segment_length,
        "metadata_json": {"mix_title": mix.title, "mix_prompt": mix.prompt},
    }


def _session_context(db: Session, request: ListeningEventCreate, user_id: int) -> dict:
    if request.session_id is None:
        raise HTTPException(status_code=422, detail="A session_id is required.")
    session = db.query(DJSession).filter(DJSession.id == request.session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="Session belongs to another user.")
    track = TRACKS.get(session.track_key)
    if track is None:
        raise HTTPException(status_code=409, detail="Session track is no longer available.")
    return {
        "session_id": session.id,
        "mix_id": None,
        "segment_id": None,
        "source": "local-demo",
        "source_track_id": f"zonix-demo-v1:{session.track_key}",
        "track_title": track["title"],
        "artist_name": track["artist"],
        "genre": "Zonix demo",
        "vibe": track["vibe"],
        "track_duration_seconds": 60,
        "segment_start_second": 0,
        "segment_end_second": 60,
        "expected_seconds": 60,
        "metadata_json": {"session_prompt": session.prompt, "track_key": session.track_key},
    }


def create_event(
    db: Session, request: ListeningEventCreate, user_id: int
) -> ListeningEvent:
    """Persist one idempotent event; track metadata is resolved server-side."""

    existing = _existing_event(db, request.client_event_id, user_id)
    if existing is not None:
        return existing

    has_mix = request.mix_id is not None or request.segment_id is not None
    has_session = request.session_id is not None
    if has_mix == has_session:
        raise HTTPException(
            status_code=422,
            detail="Provide either a mix/segment context or a session context, not both.",
        )

    context = (
        _mix_context(db, request, user_id)
        if has_mix
        else _session_context(db, request, user_id)
    )

    started_at = _utc_naive(request.started_at)
    ended_at = _utc_naive(request.ended_at)
    _reject_future_timestamp(started_at, field_name="started_at")
    _reject_future_timestamp(ended_at, field_name="ended_at")
    if ended_at is not None and started_at is not None and ended_at < started_at:
        raise HTTPException(status_code=422, detail="ended_at cannot be before started_at.")

    expected = max(1, int(context.pop("expected_seconds")))
    # Each event represents one pass through a segment/session moment. Replays
    # create a new client_event_id, so impossible over-counting is clamped here.
    seconds = min(int(request.seconds_listened), expected)
    completion_ratio = min(1.0, seconds / expected)

    event = ListeningEvent(
        client_event_id=request.client_event_id,
        user_id=user_id,
        started_at=started_at,
        ended_at=ended_at,
        seconds_listened=seconds,
        completion_ratio=round(completion_ratio, 4),
        skipped=bool(request.skipped),
        **context,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
