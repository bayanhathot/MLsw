"""Friendship, discovery, and safety helpers."""

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.database.models.profile import Profile
from app.database.models.social import Friendship, UserBlock
from app.database.models.user import User


def ordered_pair(user_id: int, other_id: int) -> tuple[int, int]:
    return (user_id, other_id) if user_id < other_id else (other_id, user_id)


def friendship(db: Session, user_id: int, other_id: int) -> Friendship | None:
    a, b = ordered_pair(user_id, other_id)
    return db.query(Friendship).filter_by(user_a_id=a, user_b_id=b).first()


def are_friends(db: Session, user_id: int, other_id: int) -> bool:
    if user_id == other_id:
        return True
    return friendship(db, user_id, other_id) is not None


def friend_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(Friendship).filter(
        or_(Friendship.user_a_id == user_id, Friendship.user_b_id == user_id)
    ).all()
    result: set[int] = set()
    for row in rows:
        result.add(row.user_b_id if row.user_a_id == user_id else row.user_a_id)
    return result


def has_block(db: Session, blocker_id: int, blocked_id: int) -> bool:
    return db.query(UserBlock).filter_by(blocker_id=blocker_id, blocked_id=blocked_id).first() is not None


def is_blocked_between(db: Session, user_id: int, other_id: int) -> bool:
    return (
        db.query(UserBlock)
        .filter(
            or_(
                and_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == other_id),
                and_(UserBlock.blocker_id == other_id, UserBlock.blocked_id == user_id),
            )
        )
        .first()
        is not None
    )



def blocked_user_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(UserBlock).filter(
        or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
    ).all()
    result: set[int] = set()
    for row in rows:
        result.add(row.blocked_id if row.blocker_id == user_id else row.blocker_id)
    return result


def relationship_status(db: Session, viewer_id: int | None, other_id: int) -> str:
    if viewer_id is None:
        return "guest"
    if viewer_id == other_id:
        return "self"
    if is_blocked_between(db, viewer_id, other_id):
        return "blocked"
    if are_friends(db, viewer_id, other_id):
        return "friends"
    from app.database.models.social import FriendRequest

    sent = db.query(FriendRequest).filter_by(sender_id=viewer_id, receiver_id=other_id, status="pending").first()
    if sent:
        return "request_sent"
    received = db.query(FriendRequest).filter_by(sender_id=other_id, receiver_id=viewer_id, status="pending").first()
    if received:
        return "request_received"
    return "none"


def public_user_card(db: Session, user: User, viewer_id: int | None = None) -> dict:
    profile = db.query(Profile).filter_by(user_id=user.id).first()
    friends = friend_ids(db, user.id)
    mutual = len(friends & friend_ids(db, viewer_id)) if viewer_id and viewer_id != user.id else 0
    return {
        "id": user.id,
        "username": user.username,
        "display_name": profile.display_name if profile else None,
        "avatar_url": profile.avatar_url if profile else None,
        "bio": profile.bio if profile else None,
        "music_interests": profile.favorite_genres if profile else None,
        "friend_count": len(friends),
        "mutual_friend_count": mutual,
        "relationship_status": relationship_status(db, viewer_id, user.id),
    }
