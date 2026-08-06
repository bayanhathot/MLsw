"""
users.py

Routes for looking up OTHER users: searching for people to friend,
viewing a public profile page, and that user's posts.

Phase 1 note:
UserProfilePage only exposes fields from the users table. Phase 3
extends the response with profile customization fields.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.routers.posts import build_post_read
from app.schemas import PostRead, UserProfilePage, UserPublic
from app.services import post_service, profile_service
from app.services.auth_service import get_user_by_username
from app.services.user_service import get_friend_status, search_users

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=list[UserPublic])
def search(
    q: str = Query(min_length=1, max_length=50),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Search for users by username, so the current user can send them a
    friend request.
    """

    results = search_users(db, query=q, viewer_id=current_user.id, limit=limit)

    return [
        UserPublic(
            id=user.id,
            username=user.username,
            friend_status=get_friend_status(db, current_user.id, user.id),
        )
        for user in results
    ]


@router.get("/{username}", response_model=UserProfilePage)
def get_profile(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    View a user's public profile page.
    """

    user = get_user_by_username(db, username)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    profile_fields = profile_service.get_public_profile_fields(db, user.id)

    return UserProfilePage(
        id=user.id,
        username=user.username,
        created_at=user.created_at,
        friend_status=get_friend_status(db, current_user.id, user.id),
        **profile_fields,
    )


@router.get("/{username}/posts", response_model=list[PostRead])
def get_user_posts(
    username: str,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    A user's own posts, shown on their profile page.
    """

    user = get_user_by_username(db, username)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    posts = post_service.get_user_posts(db, user.id, limit=limit, offset=offset)

    return [build_post_read(db, post, current_user.id) for post in posts]
