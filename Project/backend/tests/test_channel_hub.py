"""Coverage for the new ChannelHub (app.services.channel_hub) and its /ws
endpoint (app.routers.realtime): local delivery filtering, the always-on
"user:{id}" auto-subscription, publish()'s fail-open behavior when Redis
isn't configured, and the /ws authorization rules for subscribing.

NotificationHub/CommunityHub and /ws/notifications//ws/community are a
separate, still-active system (see test_forum_messaging.py) -- untouched by
any of this.
"""

import json

import pytest
import redis.asyncio as redis
from starlette.websockets import WebSocketDisconnect

from conftest import register_and_login

from app.services.channel_hub import ChannelHub


class _FakeWebSocket:
    """Minimal stand-in for the one method ChannelHub.deliver_local calls."""

    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    async def accept(self) -> None:
        pass

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(payload)


@pytest.mark.anyio
async def test_deliver_local_only_reaches_subscribers_of_the_exact_channel():
    hub = ChannelHub()
    a, b = _FakeWebSocket(), _FakeWebSocket()
    await hub.connect(a, user_id=1)
    await hub.connect(b, user_id=2)
    hub.subscribe(a, "feed:discussions")
    hub.subscribe(b, "feed:explore")

    await hub.deliver_local({"channel": "feed:discussions", "type": "post_created", "data": {}})

    assert len(a.sent) == 1
    assert a.sent[0]["channel"] == "feed:discussions"
    assert b.sent == []


@pytest.mark.anyio
async def test_deliver_local_always_reaches_the_auto_subscribed_user_channel():
    hub = ChannelHub()
    websocket = _FakeWebSocket()
    await hub.connect(websocket, user_id=42)
    # Deliberately subscribed to something unrelated -- "user:42" was added
    # automatically by connect(), not by this call.
    hub.subscribe(websocket, "feed:explore")

    await hub.deliver_local({"channel": "user:42", "type": "notification", "data": {"x": 1}})

    assert len(websocket.sent) == 1
    assert websocket.sent[0]["channel"] == "user:42"


@pytest.mark.anyio
async def test_deliver_local_drops_a_connection_that_fails_to_send():
    hub = ChannelHub()
    websocket = _FakeWebSocket(fail=True)
    await hub.connect(websocket, user_id=1)
    hub.subscribe(websocket, "feed:explore")

    await hub.deliver_local({"channel": "feed:explore", "type": "x", "data": {}})

    assert websocket not in hub._subscriptions


@pytest.mark.anyio
async def test_publish_is_a_noop_without_redis_configured(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    def unexpected_call(*args, **kwargs):
        raise AssertionError("publish must not touch Redis with no REDIS_URL configured")

    monkeypatch.setattr(redis.Redis, "publish", unexpected_call)
    hub = ChannelHub()
    await hub.publish("feed:explore", "post_created", {"id": 1})


@pytest.mark.anyio
async def test_publish_writes_the_expected_envelope_to_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis.invalid:6379/0")
    captured = {}

    async def fake_publish(self, channel, message):
        captured["channel"] = channel
        captured["message"] = message
        return 1

    monkeypatch.setattr(redis.Redis, "publish", fake_publish)
    hub = ChannelHub()
    await hub.publish("post:7", "comment_created", {"comment_id": 3})

    assert captured["channel"] == "cuemix:channel_hub"
    assert json.loads(captured["message"]) == {
        "channel": "post:7",
        "type": "comment_created",
        "data": {"comment_id": 3},
    }


def test_ws_channel_endpoint_requires_authentication(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):
            pass
    assert exc_info.value.code == 4401


def test_ws_channel_endpoint_rejects_untrusted_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws", headers={"Origin": "https://evil.example"}):
            pass
    assert exc_info.value.code == 4403


def test_ws_channel_endpoint_rejects_unauthorized_post_and_conversation_subscriptions(
    client, second_client
):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    # alice and bob are strangers: not friends, so a "friends"-visibility
    # post is invisible to bob, and a conversation channel between them
    # mirrors the same friends-only rule /messages/{username} enforces.
    post = client.post(
        "/posts",
        json={"title": "Friends only", "body": "secret", "visibility": "friends"},
    ).json()
    alice_id = client.get("/auth/me").json()["id"]

    with second_client.websocket_connect("/ws") as socket:
        socket.send_json({"action": "subscribe", "channel": f"post:{post['id']}"})
        error = socket.receive_json()
        assert error["type"] == "error"

        socket.send_json({"action": "subscribe", "channel": f"conversation:{alice_id}"})
        error = socket.receive_json()
        assert error["type"] == "error"

        # Still open after two rejections -- subscribe errors don't close
        # the connection, they just aren't honored. A third, malformed
        # frame gets its own error reply rather than the socket dying.
        socket.send_text("not json")
        error = socket.receive_json()
        assert error["type"] == "error"
