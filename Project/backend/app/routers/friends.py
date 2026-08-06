"""
friends.py

Routes for sending, responding to, and listing friend requests, plus
the accepted friends list.

Friendship model recap (see database/models/friendship.py):
    pending -> accepted
    pending -> declined
Only the addressee of a request can accept/decline it.
Only the requester can cancel a still-pending request.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models.friendship import Friendship
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import FriendRequestCreate, FriendRequestRead, UserPublic
from app.services import friend_service
from app.services.user_service import get_friend_status

router = APIRouter(prefix="/friends", tags=["friends"])


def _build_request_read(db: Session, friendship: Friendship, other_user: User, viewer_id: int) -> FriendRequestRead:
    return FriendRequestRead(
        id=friendship.id,
        other_user=UserPublic(
            id=other_user.id,
            username=other_user.username,
            friend_status=get_friend_status(db, viewer_id, other_user.id),
        ),
        status=friendship.status,
        created_at=friendship.created_at,
    )


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    return user


@router.post("/requests", response_model=FriendRequestRead, status_code=status.HTTP_201_CREATED)
def create_friend_request(
    request_data: FriendRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    friendship = friend_service.send_friend_request(
        db=db,
        requester=current_user,
        addressee_username=request_data.addressee_username,
    )

    addressee = _get_user_or_404(db, friendship.addressee_id)

    return _build_request_read(db, friendship, addressee, current_user.id)


@router.get("/requests/incoming", response_model=list[FriendRequestRead])
def get_incoming_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requests = friend_service.list_incoming_requests(db, current_user.id)

    return [
        _build_request_read(db, req, _get_user_or_404(db, req.requester_id), current_user.id)
        for req in requests
    ]


@router.get("/requests/outgoing", response_model=list[FriendRequestRead])
def get_outgoing_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requests = friend_service.list_outgoing_requests(db, current_user.id)

    return [
        _build_request_read(db, req, _get_user_or_404(db, req.addressee_id), current_user.id)
        for req in requests
    ]


@router.post("/requests/{friendship_id}/accept", response_model=FriendRequestRead)
def accept_request(
    friendship_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    friendship = friend_service.respond_to_request(db, friendship_id, current_user.id, accept=True)
    requester = _get_user_or_404(db, friendship.requester_id)

    return _build_request_read(db, friendship, requester, current_user.id)


@router.post("/requests/{friendship_id}/decline", response_model=FriendRequestRead)
def decline_request(
    friendship_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    friendship = friend_service.respond_to_request(db, friendship_id, current_user.id, accept=False)
    requester = _get_user_or_404(db, friendship.requester_id)

    return _build_request_read(db, friendship, requester, current_user.id)


@router.delete("/requests/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_request(
    friendship_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    friend_service.cancel_request(db, friendship_id, current_user.id)


@router.get("", response_model=list[UserPublic])
def get_friends(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    friends = friend_service.list_friends(db, current_user.id)

    return [
        UserPublic(
            id=friend.id,
            username=friend.username,
            friend_status="friends",
        )
        for friend in friends
    ]


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    friend_service.unfriend(db, current_user.id, username)
