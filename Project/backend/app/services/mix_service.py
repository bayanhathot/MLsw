"""Business logic for generated, persisted, and social mixes."""

from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import public_api_url
from app.database.models.mix import Mix, MixSegment
from app.database.models.mix_social import MixLike, SavedMix
from app.services.audius_service import search_tracks
from app.services.prompt_parser import parse_prompt


def local_demo_track() -> dict:
    return {
        "title": "Zonix Demo Track",
        "artist": "Zonix Demo Catalog",
        "audio_url": public_api_url("/static/audio/zonix-demo.wav"),
        "cover_url": "/brand/zonix-logo.svg",
        "duration": 60,
        "source": "local-demo",
        "source_track_id": "zonix-demo-v1",
        "genre": "Zonix demo",
        "mood": "Balanced",
    }


def create_mix(db: Session, prompt: str, owner_id: int | None = None) -> Mix:
    intent = parse_prompt(prompt)
    tracks = search_tracks(intent.search_query, limit=5)
    tracks = [
        track
        for track in tracks
        if isinstance(track, dict)
        and isinstance(track.get("audio_url"), str)
        and track["audio_url"].strip()
        and isinstance(track.get("source_track_id"), (str, int))
    ] or [local_demo_track()]
    session_id = f"mix_{uuid4().hex}"
    mix = Mix(
        session_id=session_id,
        owner_id=owner_id,
        title=prompt[:120],
        prompt=prompt,
        status="draft",
        cover_url=tracks[0].get("cover_url"),
    )
    db.add(mix)
    try:
        db.flush()
        for position, track in enumerate(tracks, start=1):
            try:
                duration = max(1, int(track.get("duration") or 60))
            except (TypeError, ValueError):
                duration = 60
            db.add(
                MixSegment(
                    mix_id=mix.id,
                    position=position,
                    title=str(track.get("title") or "Unknown title")[:255],
                    artist=str(track.get("artist") or "Unknown artist")[:255],
                    audio_url=str(track["audio_url"]),
                    cover_url=track.get("cover_url"),
                    start_second=0,
                    end_second=min(45, duration),
                    transition_to_next="crossfade" if position < len(tracks) else "end",
                    source=str(track.get("source") or "unknown")[:50],
                    source_track_id=str(track.get("source_track_id") or uuid4().hex)[:255],
                    genre=(str(track.get("genre")).strip()[:100] if track.get("genre") else None),
                    vibe=(str(track.get("mood") or intent.mood).strip()[:100] if (track.get("mood") or intent.mood) else None),
                )
            )
        db.commit()
        db.refresh(mix)
    except Exception:
        db.rollback()
        raise
    return mix


def get_mix(db: Session, mix_id: int) -> Mix | None:
    return (
        db.query(Mix)
        .options(selectinload(Mix.segments), selectinload(Mix.owner))
        .filter(Mix.id == mix_id)
        .first()
    )


def set_membership(db: Session, model, mix_id: int, user_id: int, enabled: bool) -> None:
    existing = db.query(model).filter_by(mix_id=mix_id, user_id=user_id).first()
    if enabled and existing is None:
        try:
            db.add(model(mix_id=mix_id, user_id=user_id))
            db.commit()
        except IntegrityError:
            db.rollback()
    elif not enabled and existing is not None:
        db.delete(existing)
        db.commit()


def like_count(db: Session, mix_id: int) -> int:
    return db.query(MixLike).filter(MixLike.mix_id == mix_id).count()


def liked_by(db: Session, mix_id: int, user_id: int | None) -> bool:
    return bool(
        user_id is not None
        and db.query(MixLike).filter_by(mix_id=mix_id, user_id=user_id).first()
    )


def saved_by(db: Session, mix_id: int, user_id: int | None) -> bool:
    return bool(
        user_id is not None
        and db.query(SavedMix).filter_by(mix_id=mix_id, user_id=user_id).first()
    )
