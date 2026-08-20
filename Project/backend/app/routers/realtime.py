"""Unified real-time channel endpoint (ChannelHub).

The sole real-time system for forum/messaging/social/mixes events -- see
services/channel_hub.py's module docstring. Every caller publishes through
channel_hub.
"""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import cors_origins, debug_dashboard_enabled
from app.core.security import decode_access_token
from app.database import database as db_module
from app.database.models.forum import ForumPost
from app.database.models.user import User
from app.routers.auth import ACCESS_TOKEN_COOKIE_NAME
from app.services import forum_service, social_service
from app.services.channel_hub import channel_hub

router = APIRouter(tags=["realtime"])


def _parse_channel_id(channel: str, prefix: str) -> int | None:
    try:
        return int(channel[len(prefix):])
    except ValueError:
        return None


def _authorize_subscribe(db: Session, channel: str, user_id: int) -> bool:
    """Same visibility/ownership rules as the equivalent REST GET endpoints:
    forum_service.can_view_post for "post:{id}" (see forum.py's
    _visible_or_404), social_service.are_friends for "conversation:{id}"
    (see messaging.py's /messages/{username}). "feed:{kind}" and
    "user:{own_id}" need nothing beyond the connection already being
    authenticated. "admin_debug" (routers/admin_debug.py) uses the exact
    same access rule as that router's own REST endpoints -- any
    authenticated user, gated only on the flag (see admin_debug.py's own
    docstring for why "any account" rather than "no account" or one
    specific account) -- so a subscribe attempt while the flag is off
    gets silently refused (no such channel, from this authenticated
    user's point of view) the same way the REST routes 404 rather than
    403 when disabled."""

    if channel == "admin_debug":
        return debug_dashboard_enabled()
    if channel.startswith("user:"):
        return channel == f"user:{user_id}"
    if channel.startswith("feed:"):
        return True
    if channel.startswith("post:"):
        post_id = _parse_channel_id(channel, "post:")
        if post_id is None:
            return False
        post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
        return post is not None and forum_service.can_view_post(db, post, user_id)
    if channel.startswith("conversation:"):
        other_id = _parse_channel_id(channel, "conversation:")
        if other_id is None:
            return False
        return social_service.are_friends(db, user_id, other_id)
    return False


@router.websocket("/ws")
async def channel_socket(websocket: WebSocket):
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
    with db_module.SessionLocal() as db:
        user = db.query(User).filter_by(id=user_id, is_active=True).first()
    if user is None:
        await websocket.close(code=4401)
        return

    await channel_hub.connect(websocket, user_id)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                await websocket.send_json({"type": "error", "message": "Invalid frame."})
                continue
            action = payload.get("action") if isinstance(payload, dict) else None
            channel = payload.get("channel") if isinstance(payload, dict) else None
            if action not in {"subscribe", "unsubscribe"} or not isinstance(channel, str) or not channel:
                await websocket.send_json({"type": "error", "message": "Invalid frame."})
                continue
            if action == "unsubscribe":
                channel_hub.unsubscribe(websocket, channel)
                continue
            with db_module.SessionLocal() as db:
                authorized = _authorize_subscribe(db, channel, user_id)
            if not authorized:
                await websocket.send_json(
                    {"type": "error", "message": f"Not authorized to subscribe to '{channel}'."}
                )
                continue
            channel_hub.subscribe(websocket, channel)
    except WebSocketDisconnect:
        channel_hub.disconnect(websocket)
