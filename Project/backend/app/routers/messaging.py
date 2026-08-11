"""Private messages plus durable/push notification APIs."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.core.config import cors_origins
from app.core.security import decode_access_token
from app.core.time import utc_now
from app.database.database import SessionLocal, get_db
from app.database.models.attachment import Attachment
from app.database.models.messaging import DirectMessage, Notification
from app.database.models.user import User
from app.routers.auth import ACCESS_TOKEN_COOKIE_NAME, get_current_user
from app.schemas import AttachmentRead, MessageCreate, MessageRead, NotificationRead
from app.services import forum_service
from app.services.auth_service import get_user_by_username
from app.services.notification_service import notification_hub

router = APIRouter(tags=["messaging"])


def _message_read(db: Session, message: DirectMessage) -> MessageRead:
    sender = db.query(User).filter_by(id=message.sender_id).first()
    recipient = db.query(User).filter_by(id=message.recipient_id).first()
    attachments = db.query(Attachment).filter_by(message_id=message.id).all()
    return MessageRead(
        id=message.id,
        sender_id=message.sender_id,
        sender_username=sender.username if sender else "Deleted user",
        recipient_id=message.recipient_id,
        recipient_username=recipient.username if recipient else "Deleted user",
        body=message.body,
        attachments=[AttachmentRead.model_validate(item) for item in attachments],
        created_at=message.created_at,
        read_at=message.read_at,
    )


@router.post("/messages", response_model=MessageRead, status_code=201)
async def send_message(
    request: MessageCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipient = get_user_by_username(db, request.recipient_username)
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient not found.")
    if recipient.id == current_user.id:
        raise HTTPException(status_code=422, detail="You cannot message yourself.")
    message = DirectMessage(sender_id=current_user.id, recipient_id=recipient.id, body=request.body)
    db.add(message)
    db.flush()
    forum_service.attach_owned(db, request.attachment_ids, current_user.id, "message", message.id)
    notification = forum_service.notify(
        db, recipient.id, current_user.id, "direct_message", f"New message from {current_user.username}.", "message", message.id
    )
    db.commit()
    db.refresh(message)
    message_read = _message_read(db, message)
    if notification:
        await notification_hub.publish(
            recipient.id,
            {
                **NotificationRead.model_validate(notification).model_dump(mode="json"),
                "direct_message": message_read.model_dump(mode="json"),
            },
        )
    return message_read


@router.get("/messages/{username}", response_model=list[MessageRead])
def conversation(
    username: str,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    other = get_user_by_username(db, username)
    if other is None:
        raise HTTPException(status_code=404, detail="User not found.")
    query = db.query(DirectMessage).filter(
        or_(
            (DirectMessage.sender_id == current_user.id) & (DirectMessage.recipient_id == other.id),
            (DirectMessage.sender_id == other.id) & (DirectMessage.recipient_id == current_user.id),
        )
    )
    if before_id:
        query = query.filter(DirectMessage.id < before_id)
    messages = query.order_by(DirectMessage.id.desc()).limit(limit).all()
    changed = False
    for message in messages:
        if message.recipient_id == current_user.id and message.read_at is None:
            message.read_at = utc_now()
            changed = True
    if changed:
        db.commit()
    return [_message_read(db, item) for item in reversed(messages)]


@router.get("/notifications", response_model=list[NotificationRead])
def notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Notification).filter(Notification.recipient_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.query(Notification).filter_by(id=notification_id, recipient_id=current_user.id).first()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.websocket("/ws/notifications")
async def notification_socket(websocket: WebSocket):
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin and origin not in cors_origins():
        await websocket.close(code=4403)
        return
    token = websocket.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    subject = decode_access_token(token) if token else None
    try:
        user_id = int(subject) if subject is not None else None
    except ValueError:
        user_id = None
    if user_id is None:
        await websocket.close(code=4401)
        return
    with SessionLocal() as db:
        user = db.query(User).filter_by(id=user_id, is_active=True).first()
    if user is None:
        await websocket.close(code=4401)
        return
    await notification_hub.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        notification_hub.disconnect(user_id, websocket)
