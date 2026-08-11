"""Music-first social graph: discovery, friends, blocking, and reports."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.core.time import utc_now
from app.database.database import get_db
from app.database.models.social import FriendRequest, Friendship, SocialReport, UserBlock
from app.database.models.profile import Profile
from app.database.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas import FriendRequestRead, NotificationRead, ReportCreate, UserCardRead
from app.services import forum_service, social_service
from app.services.auth_service import get_user_by_username
from app.services.notification_service import notification_hub

router = APIRouter(tags=["social graph"])


def _user_or_404(db: Session, username: str) -> User:
    user = get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def _request_read(db: Session, item: FriendRequest, viewer_id: int) -> FriendRequestRead:
    sender = db.query(User).filter_by(id=item.sender_id).first()
    receiver = db.query(User).filter_by(id=item.receiver_id).first()
    other = receiver if item.sender_id == viewer_id else sender
    card = social_service.public_user_card(db, other, viewer_id) if other else None
    return FriendRequestRead(
        id=item.id,
        sender_username=sender.username if sender else "Deleted user",
        receiver_username=receiver.username if receiver else "Deleted user",
        status=item.status,
        created_at=item.created_at,
        responded_at=item.responded_at,
        other_user=UserCardRead(**card) if card else None,
    )


@router.get("/users/search", response_model=list[UserCardRead])
def search_users(
    q: str = Query(min_length=1, max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    term = q.strip().lower()
    users = (
        db.query(User)
        .outerjoin(Profile, Profile.user_id == User.id)
        .filter(
            User.is_active.is_(True),
            User.id != current_user.id,
            or_(User.username.ilike(f"%{term}%"), Profile.display_name.ilike(f"%{term}%")),
        )
        .order_by(User.username.asc())
        .limit(limit * 2)
        .all()
    )
    users = [user for user in users if not social_service.is_blocked_between(db, current_user.id, user.id)][:limit]
    return [social_service.public_user_card(db, user, current_user.id) for user in users]


@router.get("/users/discover", response_model=list[UserCardRead])
def discover_users(
    limit: int = Query(default=12, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    users = (
        db.query(User)
        .filter(User.is_active.is_(True), User.id != current_user.id)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit * 2)
        .all()
    )
    cards = []
    for user in users:
        if social_service.is_blocked_between(db, current_user.id, user.id):
            continue
        cards.append(social_service.public_user_card(db, user, current_user.id))
        if len(cards) >= limit:
            break
    return cards


@router.get("/friends", response_model=list[UserCardRead])
def list_friends(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = social_service.friend_ids(db, current_user.id)
    if not ids:
        return []
    users = db.query(User).filter(User.id.in_(ids)).order_by(User.username.asc()).all()
    return [social_service.public_user_card(db, user, current_user.id) for user in users]


@router.get("/users/{username}/friends", response_model=list[UserCardRead])
def public_friends(
    username: str,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, username)
    if current_user is not None and social_service.has_block(db, user.id, current_user.id):
        raise HTTPException(status_code=404, detail="Profile not found.")
    ids = social_service.friend_ids(db, user.id)
    if not ids:
        return []
    users = db.query(User).filter(User.id.in_(ids)).order_by(User.username.asc()).limit(100).all()
    return [social_service.public_user_card(db, item, None) for item in users]


@router.get("/friends/requests", response_model=list[FriendRequestRead])
def friend_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(FriendRequest)
        .filter(
            or_(FriendRequest.sender_id == current_user.id, FriendRequest.receiver_id == current_user.id),
            FriendRequest.status == "pending",
        )
        .order_by(FriendRequest.created_at.desc())
        .all()
    )
    return [_request_read(db, item, current_user.id) for item in rows]


@router.post("/friends/requests/{username}", response_model=FriendRequestRead, status_code=201)
async def send_friend_request(
    username: str,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    other = _user_or_404(db, username)
    if other.id == current_user.id:
        raise HTTPException(status_code=422, detail="You cannot add yourself.")
    if social_service.is_blocked_between(db, current_user.id, other.id):
        raise HTTPException(status_code=403, detail="Friend request is unavailable.")
    if social_service.are_friends(db, current_user.id, other.id):
        raise HTTPException(status_code=409, detail="You are already friends.")

    reverse = db.query(FriendRequest).filter_by(sender_id=other.id, receiver_id=current_user.id, status="pending").first()
    if reverse:
        return await _accept_request(db, reverse, current_user)

    item = db.query(FriendRequest).filter_by(sender_id=current_user.id, receiver_id=other.id).first()
    if item and item.status == "pending":
        return _request_read(db, item, current_user.id)
    if item:
        item.status = "pending"
        item.created_at = utc_now()
        item.responded_at = None
    else:
        item = FriendRequest(sender_id=current_user.id, receiver_id=other.id, status="pending")
        db.add(item)
    notification = forum_service.notify(
        db, other.id, current_user.id, "friend_request", f"{current_user.username} sent you a friend request.", "user", current_user.id
    )
    db.commit()
    db.refresh(item)
    if notification:
        await notification_hub.publish(other.id, NotificationRead.model_validate(notification).model_dump(mode="json"))
    return _request_read(db, item, current_user.id)


async def _accept_request(db: Session, item: FriendRequest, current_user: User) -> FriendRequestRead:
    if item.receiver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can accept this request.")
    if social_service.is_blocked_between(db, item.sender_id, item.receiver_id):
        raise HTTPException(status_code=403, detail="Friend request is unavailable.")
    a, b = social_service.ordered_pair(item.sender_id, item.receiver_id)
    if not db.query(Friendship).filter_by(user_a_id=a, user_b_id=b).first():
        db.add(Friendship(user_a_id=a, user_b_id=b))
    item.status = "accepted"
    item.responded_at = utc_now()
    notification = forum_service.notify(
        db, item.sender_id, current_user.id, "friend_accepted", f"{current_user.username} accepted your friend request.", "user", current_user.id
    )
    db.commit()
    db.refresh(item)
    if notification:
        await notification_hub.publish(item.sender_id, NotificationRead.model_validate(notification).model_dump(mode="json"))
    return _request_read(db, item, current_user.id)


@router.post("/friends/requests/{request_id}/accept", response_model=FriendRequestRead)
async def accept_friend_request(
    request_id: int,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(FriendRequest).filter_by(id=request_id, status="pending").first()
    if item is None:
        raise HTTPException(status_code=404, detail="Friend request not found.")
    return await _accept_request(db, item, current_user)


@router.post("/friends/requests/{request_id}/decline", response_model=FriendRequestRead)
def decline_friend_request(
    request_id: int,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(FriendRequest).filter_by(id=request_id, receiver_id=current_user.id, status="pending").first()
    if item is None:
        raise HTTPException(status_code=404, detail="Friend request not found.")
    item.status = "declined"
    item.responded_at = utc_now()
    db.commit()
    db.refresh(item)
    return _request_read(db, item, current_user.id)


@router.delete("/friends/requests/{username}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_friend_request(
    username: str,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    other = _user_or_404(db, username)
    item = db.query(FriendRequest).filter_by(
        sender_id=current_user.id, receiver_id=other.id, status="pending"
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Pending friend request not found.")
    item.status = "cancelled"
    item.responded_at = utc_now()
    db.commit()


@router.delete("/friends/{username}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(
    username: str,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    other = _user_or_404(db, username)
    row = social_service.friendship(db, current_user.id, other.id)
    if row:
        db.delete(row)
        db.commit()


@router.post("/users/{username}/block", status_code=204)
def block_user(
    username: str,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    other = _user_or_404(db, username)
    if other.id == current_user.id:
        raise HTTPException(status_code=422, detail="You cannot block yourself.")
    if not db.query(UserBlock).filter_by(blocker_id=current_user.id, blocked_id=other.id).first():
        db.add(UserBlock(blocker_id=current_user.id, blocked_id=other.id))
    friendship = social_service.friendship(db, current_user.id, other.id)
    if friendship:
        db.delete(friendship)
    db.query(FriendRequest).filter(
        or_(
            (FriendRequest.sender_id == current_user.id) & (FriendRequest.receiver_id == other.id),
            (FriendRequest.sender_id == other.id) & (FriendRequest.receiver_id == current_user.id),
        )
    ).delete(synchronize_session=False)
    db.commit()


@router.delete("/users/{username}/block", status_code=204)
def unblock_user(
    username: str,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    other = _user_or_404(db, username)
    row = db.query(UserBlock).filter_by(blocker_id=current_user.id, blocked_id=other.id).first()
    if row:
        db.delete(row)
        db.commit()


@router.post("/reports", status_code=201)
def report_social_content(
    request: ReportCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = SocialReport(
        reporter_id=current_user.id,
        target_type=request.target_type,
        target_id=request.target_id,
        reason=request.reason,
        details=request.details,
    )
    db.add(report)
    db.commit()
    return {"status": "received", "report_id": report.id}
