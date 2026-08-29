from conftest import register_and_login


def make_friends(client, second_client):
    response = client.post("/friends/requests/bob")
    assert response.status_code == 201, response.text
    requests = second_client.get("/friends/requests").json()
    request_id = next(item["id"] for item in requests if item["sender_username"] == "alice")
    accepted = second_client.post(f"/friends/requests/{request_id}/accept")
    assert accepted.status_code == 200, accepted.text


def test_friend_request_search_and_relationship_state(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    results = client.get("/users/search?q=bob")
    assert results.status_code == 200
    assert results.json()[0]["username"] == "bob"
    assert results.json()[0]["relationship_status"] == "none"

    request = client.post("/friends/requests/bob")
    assert request.status_code == 201
    assert request.json()["other_user"]["relationship_status"] == "request_sent"

    bob_profile = second_client.get("/users/alice/profile").json()
    assert bob_profile["relationship_status"] == "request_received"

    request_id = next(
        item["id"] for item in second_client.get("/friends/requests").json()
        if item["sender_username"] == "alice"
    )
    assert second_client.post(f"/friends/requests/{request_id}/accept").status_code == 200

    assert client.get("/users/bob/profile").json()["relationship_status"] == "friends"
    assert second_client.get("/users/alice/profile").json()["relationship_status"] == "friends"
    assert client.get("/friends").json()[0]["username"] == "bob"


def test_channel_hub_receives_user_notification_on_friend_request_and_accept(client, second_client, monkeypatch):
    """social.py publishes friend-request notifications onto channel_hub's
    "user:{id}" channel (see channel_hub.py)."""

    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.social.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    alice_id = client.get("/auth/me").json()["id"]
    bob_id = second_client.get("/auth/me").json()["id"]

    assert client.post("/friends/requests/bob").status_code == 201
    channel, event_type, data = publish.await_args.args
    assert channel == f"user:{bob_id}"
    assert event_type == "notification"
    assert data["kind"] == "friend_request"

    publish.reset_mock()
    request_id = next(
        item["id"] for item in second_client.get("/friends/requests").json()
        if item["sender_username"] == "alice"
    )
    assert second_client.post(f"/friends/requests/{request_id}/accept").status_code == 200
    channel, event_type, data = publish.await_args.args
    assert channel == f"user:{alice_id}"
    assert event_type == "notification"
    assert data["kind"] == "friend_accepted"


def test_messages_are_denied_until_users_are_friends(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    denied = client.post("/messages", json={"recipient_username": "bob", "body": "hello"})
    assert denied.status_code == 403

    make_friends(client, second_client)
    allowed = client.post("/messages", json={"recipient_username": "bob", "body": "hello"})
    assert allowed.status_code == 201
    conversations = second_client.get("/conversations").json()
    assert conversations[0]["username"] == "alice"
    assert conversations[0]["unread_count"] == 1


def test_friends_only_music_identity_visibility(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    changed = client.patch(
        "/users/me/music-identity/privacy", json={"visibility": "friends"}
    )
    assert changed.status_code == 200
    assert changed.json()["visibility"] == "friends"
    assert changed.json()["is_public"] is False

    profile = second_client.get("/users/alice/profile")
    assert profile.status_code == 200
    assert profile.json()["music_identity_visibility"] == "friends"
    assert profile.json()["music_identity_public"] is False

    hidden = second_client.get("/users/alice/music-identity")
    assert hidden.status_code == 200
    assert hidden.json()["music_identity"] is None

    make_friends(client, second_client)
    visible = second_client.get("/users/alice/music-identity")
    assert visible.status_code == 200
    assert visible.json()["is_public"] is True
    assert visible.json()["music_identity"]["visibility"] == "friends"


def test_friends_feed_and_blocking(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    make_friends(client, second_client)

    post = client.post(
        "/posts",
        json={
            "body": "Friends-only music thought",
            "kind": "status",
            "visibility": "friends",
        },
    )
    assert post.status_code == 201, post.text
    friends_feed = second_client.get("/posts/feed?mode=friends")
    assert friends_feed.status_code == 200
    assert any(item["body"] == "Friends-only music thought" for item in friends_feed.json())

    assert second_client.post("/users/alice/block").status_code == 204
    assert second_client.get("/users/alice/profile").json()["relationship_status"] == "blocked"
    assert second_client.post("/messages", json={"recipient_username": "alice", "body": "nope"}).status_code == 403


def test_outgoing_friend_request_can_be_cancelled(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    assert client.post("/friends/requests/bob").status_code == 201
    assert client.delete("/friends/requests/bob").status_code == 204
    assert client.get("/users/bob/profile").json()["relationship_status"] == "none"
    assert second_client.get("/users/alice/profile").json()["relationship_status"] == "none"


def test_user_who_was_blocked_cannot_open_blockers_profile(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    assert client.post("/users/bob/block").status_code == 204
    assert second_client.get("/users/alice/profile").status_code == 404
    assert second_client.get("/users/alice/mixes").status_code == 404
