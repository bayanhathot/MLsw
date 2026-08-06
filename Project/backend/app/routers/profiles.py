"""
profiles.py

Routes for profile customization and listening stats.

Shares the "/users" prefix with routers/users.py (FastAPI allows
multiple routers on the same prefix) - these are 2-segment paths
(/users/me/profile, /users/{username}/stats) so there's no ambiguity
with users.py's 1-segment /users/{username}.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import ProfileRead, ProfileStatsRead, ProfileUpdate
from app.services import profile_service
from app.services.auth_service import get_user_by_username

router = APIRouter(prefix="/users", tags=["profiles"])


@router.get("/me/profile", response_model=ProfileRead)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = profile_service.get_or_create_profile(db, current_user.id)

    return ProfileRead.model_validate(profile)


@router.patch("/me/profile", response_model=ProfileRead)
def update_my_profile(
    update_data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = profile_service.update_profile(
        db, current_user.id, update_data.model_dump(exclude_unset=True)
    )

    return ProfileRead.model_validate(profile)


@router.get("/{username}/stats", response_model=ProfileStatsRead)
def get_user_stats(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, username)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    minutes_listened, favorite_artists = profile_service.compute_stats(db, user.id)

    return ProfileStatsRead(minutes_listened=minutes_listened, favorite_artists=favorite_artists)
