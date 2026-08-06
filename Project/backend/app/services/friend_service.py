"""
friend_service.py

Business logic for sending, responding to, and listing friend requests.

The router handles HTTP.
This file handles the actual friendship state machine.
"""

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database.models.friendship import Friendship
from app.database.models.user import User
from app.services.user_service import get_friendship_between, get_user_by_username


def send_friend_request(db: Session, requester: User, addressee_username: str) -> Friendship:
    """
    Send a friend request from requester to the user named addressee_username.

    Steps:
    1. Find the addressee by username.
    2. Reject requests to yourself.
    3. Reject if a pending/accepted friendship already exists (either direction).
    4. If a declined friendship exists, reuse the row instead of inserting a new one.
    5. Otherwise create a new pending friendship row.
    """

    addressee = get_user_by_username(db, addressee_username)

    if addressee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if addressee.id == requester.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a friend request to yourself.",
        )

    existing = get_friendship_between(db, requester.id, addressee.id)

    if existing is not None and existing.status in {"pending", "accepted"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A friend request already exists between these users.",
        )

    if existing is not None and existing.status == "declined":
        existing.requester_id = requester.id
        existing.addressee_id = addressee.id
        existing.status = "pending"
        existing.responded_at = None
        db.commit()
        db.refresh(existing)
        return existing

    friendship = Friendship(
        requester_id=requester.id,
        addressee_id=addressee.id,
        status="pending",
    )

    db.add(friendship)
    db.commit()
    db.refresh(friendship)

    return friendship


def list_incoming_requests(db: Session, user_id: int) -> list[Friendship]:
    """
    Pending requests where the current user is the addressee.
    """

    return (
        db.query(Friendship)
        .filter(Friendship.addressee_id == user_id, Friendship.status == "pending")
        .order_by(Friendship.created_at.desc())
        .all()
    )


def list_outgoing_requests(db: Session, user_id: int) -> list[Friendship]:
    """
    Pending requests the current user has sent.
    """

    return (
        db.query(Friendship)
        .filter(Friendship.requester_id == user_id, Friendship.status == "pending")
        .order_by(Friendship.created_at.desc())
        .all()
    )


def _get_friendship_or_404(db: Session, friendship_id: int) -> Friendship:
    friendship = db.query(Friendship).filter(Friendship.id == friendship_id).first()

    if friendship is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Friend request not found.",
        )

    return friendship


def respond_to_request(db: Session, friendship_id: int, current_user_id: int, accept: bool) -> Friendship:
    """
    Accept or decline a pending friend request.

    Only the addressee may respond.
    """

    friendship = _get_friendship_or_404(db, friendship_id)

    if friendship.addressee_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the recipient of a friend request can respond to it.",
        )

    if friendship.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This friend request has already been resolved.",
        )

    friendship.status = "accepted" if accept else "declined"
    friendship.responded_at = datetime.utcnow()

    db.commit()
    db.refresh(friendship)

    return friendship


def cancel_request(db: Session, friendship_id: int, current_user_id: int) -> None:
    """
    Cancel a friend request you sent, before it has been responded to.

    Only the requester may cancel.
    """

    friendship = _get_friendship_or_404(db, friendship_id)

    if friendship.requester_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the sender of a friend request can cancel it.",
        )

    if friendship.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This friend request has already been resolved.",
        )

    db.delete(friendship)
    db.commit()


def list_friends(db: Session, user_id: int) -> list[User]:
    """
    List all users the given user is friends with (accepted friendships,
    read from either direction).
    """

    friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
        )
        .all()
    )

    friend_ids = [
        f.addressee_id if f.requester_id == user_id else f.requester_id for f in friendships
    ]

    if not friend_ids:
        return []

    return db.query(User).filter(User.id.in_(friend_ids)).order_by(User.username).all()


def get_friend_ids(db: Session, user_id: int) -> list[int]:
    """
    Like list_friends, but returns just the ids.

    Used by the feed query in a later phase, and by unfriend/profile checks.
    """

    friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
        )
        .all()
    )

    return [f.addressee_id if f.requester_id == user_id else f.requester_id for f in friendships]


def unfriend(db: Session, user_id: int, other_username: str) -> None:
    """
    Remove an accepted friendship between the current user and other_username.
    """

    other_user = get_user_by_username(db, other_username)

    if other_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    friendship = get_friendship_between(db, user_id, other_user.id)

    if friendship is None or friendship.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not friends with this user.",
        )

    db.delete(friendship)
    db.commit()
