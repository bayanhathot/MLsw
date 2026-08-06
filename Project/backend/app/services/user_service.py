"""
user_service.py

Business logic for public user lookup: search and profile viewing.

This is distinct from auth_service.py, which handles registration/login
for the CURRENT user. This file answers questions about OTHER users,
from the point of view of whoever is logged in (the viewer).
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database.models.friendship import Friendship
from app.database.models.user import User
from app.services.auth_service import get_user_by_username


def search_users(db: Session, query: str, viewer_id: int, limit: int = 20) -> list[User]:
    """
    Search users by username, excluding the viewer.

    Uses a simple case-insensitive "contains" match, good enough for
    this project's scale.
    """

    return (
        db.query(User)
        .filter(User.username.ilike(f"%{query}%"))
        .filter(User.id != viewer_id)
        .order_by(User.username)
        .limit(limit)
        .all()
    )


def get_friendship_between(db: Session, user_id_a: int, user_id_b: int) -> Friendship | None:
    """
    Find the friendship row between two users, regardless of who
    originally sent the request.
    """

    return (
        db.query(Friendship)
        .filter(
            or_(
                (Friendship.requester_id == user_id_a) & (Friendship.addressee_id == user_id_b),
                (Friendship.requester_id == user_id_b) & (Friendship.addressee_id == user_id_a),
            )
        )
        .first()
    )


def get_friend_status(db: Session, viewer_id: int, target_id: int) -> str:
    """
    Compute the friendship status of target_id, relative to viewer_id.

    Returns one of: "self", "none", "pending_outgoing", "pending_incoming", "friends".
    """

    if viewer_id == target_id:
        return "self"

    friendship = get_friendship_between(db, viewer_id, target_id)

    if friendship is None or friendship.status == "declined":
        return "none"

    if friendship.status == "accepted":
        return "friends"

    # status == "pending"
    if friendship.requester_id == viewer_id:
        return "pending_outgoing"

    return "pending_incoming"


__all__ = ["search_users", "get_friendship_between", "get_friend_status", "get_user_by_username"]
