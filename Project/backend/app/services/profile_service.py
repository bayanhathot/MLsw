"""
profile_service.py

Business logic for profile customization and computed listening stats.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models.mix import MixSegment
from app.database.models.play_event import PlayEvent
from app.database.models.profile import Profile

# How many artists to surface in the "favorite artists" ranking.
FAVORITE_ARTISTS_LIMIT = 5


def get_or_create_profile(db: Session, user_id: int) -> Profile:
    """
    Return the user's profile, creating a default one on first access.

    This means the API never has to represent a "no profile yet" state -
    every user effectively always has one.
    """

    profile = db.query(Profile).filter(Profile.user_id == user_id).first()

    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


def get_public_profile_fields(db: Session, user_id: int) -> dict:
    """
    Read-only view of another user's customizable profile fields, for
    GET /users/{username}. Unlike get_or_create_profile, this never
    writes - viewing someone's profile shouldn't create a row for them.
    """

    profile = db.query(Profile).filter(Profile.user_id == user_id).first()

    if profile is None:
        return {"display_name": None, "avatar_url": None, "bio": None, "favorite_genres": None}

    return {
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "bio": profile.bio,
        "favorite_genres": profile.favorite_genres,
    }


def update_profile(db: Session, user_id: int, updates: dict) -> Profile:
    """
    Apply only the fields present in `updates` (see ProfileUpdate's
    exclude_unset=True usage in the router) - omitted fields are left
    untouched, not cleared.
    """

    profile = get_or_create_profile(db, user_id)

    for field, value in updates.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)

    return profile


def compute_stats(db: Session, user_id: int) -> tuple[int, list[dict]]:
    """
    Compute minutes_listened and the top favorite_artists from
    play_events, on demand (not stored/denormalized anywhere).
    """

    total_seconds = (
        db.query(func.coalesce(func.sum(PlayEvent.seconds_listened), 0))
        .filter(PlayEvent.user_id == user_id)
        .scalar()
    )

    rows = (
        db.query(MixSegment.artist, func.sum(PlayEvent.seconds_listened).label("total_seconds"))
        .join(PlayEvent, PlayEvent.segment_id == MixSegment.id)
        .filter(PlayEvent.user_id == user_id)
        .group_by(MixSegment.artist)
        .order_by(func.sum(PlayEvent.seconds_listened).desc())
        .limit(FAVORITE_ARTISTS_LIMIT)
        .all()
    )

    favorite_artists = [
        {"artist": artist, "seconds_listened": int(total_seconds_for_artist)}
        for artist, total_seconds_for_artist in rows
    ]

    return total_seconds // 60, favorite_artists
