import time

from conftest import register_and_login


def _upload_audio(uploading_client, filename="clip.mp3"):
    job = uploading_client.post(
        "/uploads/jobs",
        content=b"ID3" + b"\x00" * 16,
        headers={"Content-Type": "audio/mpeg", "X-Filename": filename},
    ).json()
    for _ in range(100):
        job = uploading_client.get(f"/uploads/jobs/{job['job_id']}").json()
        if job["status"] == "completed" and job["attachment"]:
            break
        time.sleep(0.005)
    return job["attachment"]


def _make_friends(client, second_client, receiver_username="bob", sender_username="alice"):
    request = client.post(f"/friends/requests/{receiver_username}")
    assert request.status_code == 201
    request_id = next(
        item["id"] for item in second_client.get("/friends/requests").json()
        if item["sender_username"] == sender_username
    )
    assert second_client.post(f"/friends/requests/{request_id}/accept").status_code == 200


def test_public_anonymous_post_comment_votes_and_profile_stats(client, second_client, monkeypatch):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.channel_hub.publish", publish)
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
    # Replaying an identical vote is idempotent and sends no extra notification
    # (channel_hub.publish still fires a "vote_changed" event on every vote
    # attempt regardless, so only the "notification"-typed calls are counted).
    assert second_client.post(f"/posts/{post['id']}/vote", json={"value": 1}).json()["score"] == 1
    assert len(client.get("/notifications").json()) == 1
    notification_calls = [call for call in publish.await_args_list if call.args[1] == "notification"]
    assert len(notification_calls) == 1
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
    assert stats["comment_count"] == 1
    assert stats["received_downvotes"] == 1


def test_direct_messages_are_private_and_notify(client, second_client, monkeypatch):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.messaging.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    # Direct messages are intentionally friend-only in the social product.
    request = client.post("/friends/requests/bob")
    assert request.status_code == 201
    incoming = second_client.get("/friends/requests").json()
    request_id = next(item["id"] for item in incoming if item["sender_username"] == "alice")
    assert second_client.post(f"/friends/requests/{request_id}/accept").status_code == 200

    sent = client.post(
        "/messages", json={"recipient_username": "bob", "body": "private hello"}
    )
    assert sent.status_code == 201
    assert sent.json()["sender_username"] == "alice"
    # channel_hub is a shared singleton, so this monkeypatch also captures
    # the friend-request/accept notifications above -- only the most recent
    # "notification"-typed call is the direct-message one under test.
    notification_calls = [call for call in publish.await_args_list if call.args[1] == "notification"]
    pushed = notification_calls[-1].args[2]
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
    monkeypatch.setattr("app.routers.forum.channel_hub.publish", publish)
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
    notification_calls = [call for call in publish.await_args_list if call.args[1] == "notification"]
    pushed = notification_calls[0].args[2]
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


def test_profile_rejects_invalid_music_interests_without_changing_saved_profile(client):
    register_and_login(client)
    saved = client.patch(
        "/users/me/profile", json={"favorite_genres": ["House", "Jazz"]}
    )
    assert saved.status_code == 200
    assert saved.json()["favorite_genres"] == ["house", "jazz"]

    invalid_lists = [
        [f"genre-{index}" for index in range(21)],
        ["House", "house"],
        ["House", "   "],
        ["x" * 41],
    ]
    for favorite_genres in invalid_lists:
        response = client.patch(
            "/users/me/profile", json={"favorite_genres": favorite_genres}
        )
        assert response.status_code == 422

    assert client.get("/users/me/profile").json()["favorite_genres"] == [
        "house",
        "jazz",
    ]


def test_friends_only_post_attachment_is_hidden_from_non_friends(client, second_client, third_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    register_and_login(third_client, "carol", "carol@example.com")
    _make_friends(client, second_client)

    attachment = _upload_audio(client)
    post = client.post(
        "/posts",
        json={
            "body": "Friends-only track",
            "kind": "status",
            "visibility": "friends",
            "attachment_ids": [attachment["id"]],
        },
    ).json()
    path = attachment["url"].removeprefix("/api")

    # Owner and accepted friend can retrieve the media.
    assert client.get(path).status_code == 200
    assert second_client.get(path).status_code == 200
    # A signed-in stranger and a fully anonymous guest cannot guess the
    # attachment ID to bypass the post's friends-only visibility.
    assert third_client.get(path).status_code == 403
    third_client.post("/auth/logout")
    assert third_client.get(path).status_code == 403


def test_comment_attachment_is_hidden_after_the_author_is_blocked(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Public", "body": "hello"}).json()

    attachment = _upload_audio(second_client, "reply.mp3")
    second_client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "reply with media", "attachment_ids": [attachment["id"]]},
    )
    path = attachment["url"].removeprefix("/api")

    assert client.get(path).status_code == 200
    assert client.post("/users/bob/block").status_code == 204
    assert client.get(path).status_code == 403


def test_comment_list_hides_entries_from_a_blocked_author(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Public", "body": "hello"}).json()
    comment = second_client.post(f"/posts/{post['id']}/comments", json={"body": "hi"}).json()

    visible = client.get(f"/posts/{post['id']}/comments").json()
    assert any(item["id"] == comment["id"] for item in visible)

    assert client.post("/users/bob/block").status_code == 204
    after_block = client.get(f"/posts/{post['id']}/comments").json()
    assert not any(item["id"] == comment["id"] for item in after_block)


def test_blocked_comment_author_cannot_be_voted_on_by_direct_id(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Public", "body": "hello"}).json()
    comment = second_client.post(f"/posts/{post['id']}/comments", json={"body": "hi"}).json()

    # Voting works normally before any block exists.
    assert client.post(f"/posts/comments/{comment['id']}/vote", json={"value": 1}).status_code == 200

    assert client.post("/users/bob/block").status_code == 204
    # Blocking the comment's author must also close the direct-ID vote path,
    # not just hide the comment from the list endpoint.
    assert client.post(f"/posts/comments/{comment['id']}/vote", json={"value": 1}).status_code == 404
    assert client.delete(f"/posts/comments/{comment['id']}/vote").status_code == 404


def test_conversations_are_bounded_to_friends_and_paginated(client, second_client, third_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    register_and_login(third_client, "carol", "carol@example.com")
    _make_friends(client, second_client)

    request = client.post("/friends/requests/carol")
    assert request.status_code == 201
    request_id = next(
        item["id"] for item in third_client.get("/friends/requests").json()
        if item["sender_username"] == "alice"
    )
    assert third_client.post(f"/friends/requests/{request_id}/accept").status_code == 200

    assert client.post("/messages", json={"recipient_username": "bob", "body": "hi bob"}).status_code == 201
    assert client.post("/messages", json={"recipient_username": "carol", "body": "hi carol"}).status_code == 201

    conversations = client.get("/conversations").json()
    assert {item["username"] for item in conversations} == {"bob", "carol"}

    limited = client.get("/conversations?limit=1").json()
    assert len(limited) == 1


def test_channel_hub_receives_typed_events_for_posts_and_comments(client, second_client, monkeypatch):
    """channel_hub.publish (see services/channel_hub.py) is the sole
    real-time system: every forum write emits a typed event on the matching
    "post:{id}"/"feed:{kind}" channel, plus a "user:{author_id}" mirror of
    any Notification that was created."""

    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    post = client.post("/posts", json={"title": "Hello", "body": "world", "kind": "discussion"}).json()
    channel, event_type, data = publish.await_args.args
    assert channel == "feed:discussion"
    assert event_type == "feed_changed"
    assert data == {"kind": "discussion"}
    assert post["title"] not in repr(data)

    publish.reset_mock()
    voted = second_client.post(f"/posts/{post['id']}/vote", json={"value": 1}).json()
    calls = {call.args[0]: call.args for call in publish.await_args_list}
    assert calls[f"user:{post['author_id']}"][1] == "notification"
    assert calls[f"post:{post['id']}"] == (f"post:{post['id']}", "vote_changed", {"score": voted["score"]})

    publish.reset_mock()
    comment = second_client.post(
        f"/posts/{post['id']}/comments", json={"body": "nice", "is_anonymous": False}
    ).json()
    calls = {call.args[0]: call.args for call in publish.await_args_list}
    assert calls[f"user:{post['author_id']}"][1] == "notification"
    assert calls[f"post:{post['id']}"] == (
        f"post:{post['id']}",
        "comments_changed",
        {"post_id": post["id"]},
    )
    assert comment["body"] not in repr(calls[f"post:{post['id']}"])

    publish.reset_mock()
    comment_vote = client.post(f"/posts/comments/{comment['id']}/vote", json={"value": 1}).json()
    calls = {call.args[0]: call.args for call in publish.await_args_list}
    assert calls[f"user:{comment['author_id']}"][1] == "notification"
    assert calls[f"post:{post['id']}"] == (
        f"post:{post['id']}",
        "comment_vote_changed",
        {"comment_id": comment["id"], "score": comment_vote["score"]},
    )

    publish.reset_mock()
    # Only bob (the comment's author) may delete it.
    assert second_client.delete(f"/posts/{post['id']}/comments/{comment['id']}").status_code == 204
    channel, event_type, data = publish.await_args.args
    assert channel == f"post:{post['id']}"
    assert event_type == "comments_changed"
    assert data == {"post_id": post["id"]}


def test_channel_hub_receives_message_created_on_exact_pair_channel(client, second_client, monkeypatch):
    """A DM uses one channel containing both participant ids, plus the
    recipient's private notification channel."""

    from unittest.mock import AsyncMock

    from app.services.channel_hub import conversation_channel

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.messaging.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    _make_friends(client, second_client)
    alice_id = client.get("/auth/me").json()["id"]
    bob_id = second_client.get("/auth/me").json()["id"]

    assert client.post("/messages", json={"recipient_username": "bob", "body": "hi bob"}).status_code == 201

    calls = {call.args[0]: call.args for call in publish.await_args_list}
    assert calls[f"user:{bob_id}"][1] == "notification"
    pair_channel = conversation_channel(alice_id, bob_id)
    assert calls[pair_channel][1] == "message_created"
    assert calls[pair_channel][2]["body"] == "hi bob"
    assert len([call for call in publish.await_args_list if call.args[1] == "message_created"]) == 1


def test_friends_only_feed_events_never_reach_a_stranger_or_contain_post_data(
    client, second_client, third_client, monkeypatch
):
    """Friends-only feed changes target only the author/current friends and
    carry a REST-refresh signal instead of the post's private fields."""

    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.channel_hub.publish", publish)
    alice = register_and_login(client, "alice", "alice@example.com")
    bob = register_and_login(second_client, "bob", "bob@example.com")
    carol = register_and_login(third_client, "carol", "carol@example.com")
    _make_friends(client, second_client)
    publish.reset_mock()

    secret_title = "private title for accepted friends"
    secret_body = "private body that must never enter a shared feed"
    created = client.post(
        "/posts",
        json={
            "title": secret_title,
            "body": secret_body,
            "kind": "discussion",
            "visibility": "friends",
        },
    )
    assert created.status_code == 201

    calls = [call.args for call in publish.await_args_list]
    assert {call[0] for call in calls} == {f"user:{alice['id']}", f"user:{bob['id']}"}
    assert all(call[1:] == ("feed_changed", {"kind": "discussion"}) for call in calls)
    assert all(call[0] != f"user:{carol['id']}" for call in calls)
    assert all(not call[0].startswith("feed:") for call in calls)
    assert secret_title not in repr(calls)
    assert secret_body not in repr(calls)

    publish.reset_mock()
    assert client.delete(f"/posts/{created.json()['id']}").status_code == 204
    feed_calls = [call.args for call in publish.await_args_list if call.args[1] == "feed_changed"]
    assert {call[0] for call in feed_calls} == {f"user:{alice['id']}", f"user:{bob['id']}"}
    assert all(call[2] == {"kind": "discussion"} for call in feed_calls)
    assert all(call[0] != f"user:{carol['id']}" for call in feed_calls)
