"""Authenticated user follow and follower endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, aliased

from app.database.database import get_db
from app.database.models.user import User
from app.database.models.user_follow import UserFollow
from app.routers.auth import get_current_user
from app.schemas import FollowState, UserSummary


router = APIRouter(prefix="/users", tags=["users"])


def get_active_user_or_404(db: Session, user_id: int) -> User:
    """Return an active public user or raise a consistent 404 response."""

    user = (
        db.query(User)
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.put("/{user_id}/follow", response_model=FollowState)
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Follow a creator. Repeating the request keeps the same final state."""

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot follow yourself.",
        )

    get_active_user_or_404(db, user_id)

    relationship = (
        db.query(UserFollow)
        .filter(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == user_id,
        )
        .first()
    )

    if relationship is None:
        db.add(
            UserFollow(
                follower_id=current_user.id,
                following_id=user_id,
            )
        )
        db.commit()

    return {"user_id": user_id, "is_following": True}


@router.delete("/{user_id}/follow", response_model=FollowState)
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove only the current user's follow relationship."""

    relationship = (
        db.query(UserFollow)
        .filter(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == user_id,
        )
        .first()
    )

    if relationship is not None:
        db.delete(relationship)
        db.commit()

    return {"user_id": user_id, "is_following": False}


@router.get("/me/following", response_model=list[UserSummary])
def get_following(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return creators followed by the current user."""

    return (
        db.query(User)
        .join(UserFollow, UserFollow.following_id == User.id)
        .filter(UserFollow.follower_id == current_user.id)
        .order_by(User.username.asc())
        .all()
    )


@router.get("/me/followers", response_model=list[UserSummary])
def get_followers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return users who follow the current user."""

    return (
        db.query(User)
        .join(UserFollow, UserFollow.follower_id == User.id)
        .filter(UserFollow.following_id == current_user.id)
        .order_by(User.username.asc())
        .all()
    )


@router.get("/me/friends", response_model=list[UserSummary])
def get_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return users who have a mutual follow with the current user."""

    outgoing = aliased(UserFollow)
    incoming = aliased(UserFollow)

    return (
        db.query(User)
        .join(outgoing, outgoing.following_id == User.id)
        .join(incoming, incoming.follower_id == User.id)
        .filter(
            outgoing.follower_id == current_user.id,
            incoming.following_id == current_user.id,
        )
        .order_by(User.username.asc())
        .all()
    )
