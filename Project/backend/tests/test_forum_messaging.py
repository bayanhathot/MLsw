from conftest import register_and_login
import pytest
from starlette.websockets import WebSocketDisconnect


def test_public_anonymous_post_comment_votes_and_profile_stats(client, second_client, monkeypatch):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.notification_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post_response = client.post(
        "/posts",
        json={"title": "A useful idea", "body": "Try this transition.", "is_anonymous": True},
    )
    assert post_response.status_code == 201
    post = post_response.json()
    assert post["author_username"] == "Anonymous"
    assert post["author_id"] is None
    assert post["can_delete"] is True
    other_view = second_client.get("/posts/feed").json()[0]
    assert other_view["title"] == "A useful idea"
    assert other_view["can_delete"] is False
    assert second_client.delete(f"/posts/{post['id']}").status_code == 403

    voted = second_client.post(f"/posts/{post['id']}/vote", json={"value": 1})
    assert voted.json()["score"] == 1
    assert voted.json()["my_vote"] == 1
    # Replaying an identical vote is idempotent and sends no extra notification.
    assert second_client.post(f"/posts/{post['id']}/vote", json={"value": 1}).json()["score"] == 1
    assert len(client.get("/notifications").json()) == 1
    assert publish.await_count == 1
    # Upsert changes the vote instead of creating two reactions.
    assert second_client.post(f"/posts/{post['id']}/vote", json={"value": -1}).json()["score"] == -1

    comment = second_client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Nice!", "is_anonymous": False},
    ).json()
    assert comment["author_username"] == "bob"
    assert comment["can_delete"] is True
    assert client.post(f"/posts/comments/{comment['id']}/vote", json={"value": 1}).json()["score"] == 1
    stats = client.get("/users/alice/stats").json()
    assert stats["post_count"] == 1
    assert stats["received_downvotes"] == 1


def test_direct_messages_are_private_and_notify(client, second_client, monkeypatch):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.messaging.notification_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    sent = client.post(
        "/messages", json={"recipient_username": "bob", "body": "private hello"}
    )
    assert sent.status_code == 201
    assert sent.json()["sender_username"] == "alice"
    pushed = publish.await_args.args[1]
    assert pushed["kind"] == "direct_message"
    assert pushed["direct_message"]["body"] == "private hello"
    history = second_client.get("/messages/alice")
    assert history.status_code == 200
    assert history.json()[0]["body"] == "private hello"
    notices = second_client.get("/notifications?unread_only=true").json()
    assert notices[0]["kind"] == "direct_message"
    assert second_client.post(f"/notifications/{notices[0]['id']}/read").json()["is_read"] is True
    assert client.get("/messages/nobody").status_code == 404


def test_anonymous_comment_notification_does_not_reveal_author(client, second_client, monkeypatch):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.notification_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post(
        "/posts", json={"title": "Privacy", "body": "Anonymous replies welcome."}
    ).json()

    comment = second_client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Private identity", "is_anonymous": True},
    )
    assert comment.status_code == 201
    assert comment.json()["author_username"] == "Anonymous"
    persisted = client.get("/notifications").json()[0]
    pushed = publish.await_args.args[1]
    assert persisted["message"] == "Someone commented on your post."
    assert pushed["message"] == "Someone commented on your post."
    assert "bob" not in persisted["message"].lower()
    assert "bob" not in pushed["message"].lower()


def test_profile_partial_updates(client):
    register_and_login(client)
    assert client.get("/users/me/profile").json()["theme_preference"] == "dark"
    assert client.patch(
        "/users/me/profile", json={"display_name": "Alice", "favorite_genres": ["House", "Lofi"]}
    ).status_code == 200
    profile = client.patch("/users/me/profile", json={"bio": "music fan"}).json()
    assert profile["display_name"] == "Alice"
    assert profile["favorite_genres"] == ["house", "lofi"]
    assert profile["bio"] == "music fan"


def test_notification_websocket_rejects_untrusted_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/notifications", headers={"Origin": "https://evil.example"}
        ):
            pass
    assert exc_info.value.code == 4403
