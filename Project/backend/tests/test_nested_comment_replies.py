"""forum_comments.parent_comment_id (single-level nested replies) --
routers/forum.py's create_comment validates the parent, forum_service
notifies the parent comment's author distinctly from the post author, and
deleting a parent comment cascades to its replies."""

from conftest import register_and_login


def test_reply_is_linked_to_its_parent_and_returned_in_the_thread(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    top = second_client.post(f"/posts/{post['id']}/comments", json={"body": "Nice find!"}).json()
    assert top["parent_comment_id"] is None

    reply = client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Thanks, glad you liked it!", "parent_comment_id": top["id"]},
    )
    assert reply.status_code == 201
    assert reply.json()["parent_comment_id"] == top["id"]

    thread = client.get(f"/posts/{post['id']}/comments").json()
    assert len(thread) == 2
    by_id = {item["id"]: item for item in thread}
    assert by_id[top["id"]]["parent_comment_id"] is None
    assert by_id[reply.json()["id"]]["parent_comment_id"] == top["id"]


def test_cannot_reply_to_a_reply(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    top = second_client.post(f"/posts/{post['id']}/comments", json={"body": "Nice find!"}).json()
    reply = client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Thanks!", "parent_comment_id": top["id"]},
    ).json()

    nested = second_client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Replying to a reply", "parent_comment_id": reply["id"]},
    )
    assert nested.status_code == 422


def test_cannot_reply_to_a_comment_on_a_different_post(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post_a = client.post("/posts", json={"title": "Post A", "body": "First."}).json()
    post_b = client.post("/posts", json={"title": "Post B", "body": "Second."}).json()
    comment_on_a = second_client.post(
        f"/posts/{post_a['id']}/comments", json={"body": "On A"}
    ).json()

    response = second_client.post(
        f"/posts/{post_b['id']}/comments",
        json={"body": "Cross-post reply", "parent_comment_id": comment_on_a["id"]},
    )
    assert response.status_code == 422


def test_replying_to_a_nonexistent_comment_is_rejected(client):
    register_and_login(client, "alice", "alice@example.com")
    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    response = client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Reply to nothing", "parent_comment_id": 999999},
    )
    assert response.status_code == 404


def test_deleting_a_parent_comment_cascades_to_its_replies(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    top = second_client.post(f"/posts/{post['id']}/comments", json={"body": "Nice find!"}).json()
    reply = client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Thanks!", "parent_comment_id": top["id"]},
    ).json()

    deleted = second_client.delete(f"/posts/{post['id']}/comments/{top['id']}")
    assert deleted.status_code == 204

    thread = client.get(f"/posts/{post['id']}/comments").json()
    assert thread == []
    # The reply is gone too (cascade), not orphaned with a dangling parent_comment_id.
    assert not any(item["id"] == reply["id"] for item in thread)


def test_reply_notifies_the_parent_comment_author_distinctly_from_the_post_author(
    client, second_client, third_client, monkeypatch
):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")  # post author
    register_and_login(second_client, "bob", "bob@example.com")  # top-level commenter
    register_and_login(third_client, "carol", "carol@example.com")  # replier

    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    top = second_client.post(f"/posts/{post['id']}/comments", json={"body": "Nice find!"}).json()
    third_client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Agreed!", "parent_comment_id": top["id"]},
    )

    alice_notifications = client.get("/notifications").json()
    bob_notifications = second_client.get("/notifications").json()
    assert any(item["kind"] == "comment" for item in alice_notifications)
    assert any(item["kind"] == "comment_reply" for item in bob_notifications)


def test_reply_does_not_double_notify_when_parent_author_is_the_post_author(
    client, second_client, monkeypatch
):
    from unittest.mock import AsyncMock

    publish = AsyncMock()
    monkeypatch.setattr("app.routers.forum.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    top = client.post(f"/posts/{post['id']}/comments", json={"body": "My own top comment"}).json()
    second_client.post(
        f"/posts/{post['id']}/comments",
        json={"body": "Reply to the author's own comment", "parent_comment_id": top["id"]},
    )

    alice_notifications = client.get("/notifications").json()
    # Only one notification: forum_service.notify already self-suppresses,
    # and create_comment skips the second notify call outright when the
    # parent comment's author is the same as the post's author.
    assert len(alice_notifications) == 1
    assert alice_notifications[0]["kind"] == "comment"
