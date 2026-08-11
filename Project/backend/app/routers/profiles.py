"""Authenticated profile settings and public engagement dashboard."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.core.rate_limit import write_rate_limit
from app.database.models.user import User
from app.database.models.session import UserPreference
from app.routers.auth import get_current_user
from app.schemas import PreferenceRead, ProfileRead, ProfileStatsRead, ProfileUpdate
from app.services import profile_service
from app.services.auth_service import get_user_by_username

router = APIRouter(prefix="/users", tags=["profiles"])


@router.get("/me/profile", response_model=ProfileRead)
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_service.get_or_create(db, current_user.id)


@router.patch("/me/profile", response_model=ProfileRead)
def update_profile(request: ProfileUpdate, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = profile_service.get_or_create(db, current_user.id)
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/me/preferences", response_model=list[PreferenceRead])
def get_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(UserPreference)
        .filter(UserPreference.user_id == current_user.id)
        .order_by(UserPreference.score.desc(), UserPreference.count.desc())
        .all()
    )


@router.get("/{username}/stats", response_model=ProfileStatsRead)
def profile_stats(username: str, db: Session = Depends(get_db)):
    user = get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return profile_service.engagement_stats(db, user.id)
