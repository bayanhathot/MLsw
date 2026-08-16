"""Community/forum/social read and write endpoints must reject anonymous
requests outright (401), not silently degrade to guest-visible data. Covers
the routers/forum.py and routers/social.py endpoints that used to accept
get_optional_current_user."""

from fastapi.testclient import TestClient

from conftest import register_and_login

from app.main import app


def anonymous():
    """A fresh, never-logged-in TestClient against the same app instance --
    `client`/`second_client` may already carry a session cookie by the time
    a test wants to check unauthenticated behavior."""

    return TestClient(app)


def _seed_post(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    post = client.post("/posts", json={"title": "Track pick", "body": "Try this one."}).json()
    comment = second_client.post(f"/posts/{post['id']}/comments", json={"body": "Nice find!"}).json()
    return post, comment


def test_anonymous_cannot_read_the_feed(client):
    for mode in ("explore", "friends", "discussions"):
        response = client.get(f"/posts/feed?mode={mode}")
        assert response.status_code == 401, (mode, response.text)


def test_logged_in_user_can_still_read_the_feed(client, second_client):
    _seed_post(client, second_client)
    response = client.get("/posts/feed?mode=explore")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_anonymous_cannot_read_a_single_post(client, second_client):
    post, _ = _seed_post(client, second_client)
    response = anonymous().get(f"/posts/{post['id']}")
    assert response.status_code == 401


def test_logged_in_user_can_still_read_a_single_post(client, second_client):
    post, _ = _seed_post(client, second_client)
    response = second_client.get(f"/posts/{post['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == post["id"]


def test_anonymous_cannot_read_comments(client, second_client):
    post, _ = _seed_post(client, second_client)
    response = anonymous().get(f"/posts/{post['id']}/comments")
    assert response.status_code == 401


def test_logged_in_user_can_still_read_comments(client, second_client):
    post, comment = _seed_post(client, second_client)
    response = client.get(f"/posts/{post['id']}/comments")
    assert response.status_code == 200
    assert response.json()[0]["id"] == comment["id"]


def test_anonymous_cannot_create_a_post(client):
    response = client.post("/posts", json={"title": "x", "body": "y"})
    assert response.status_code == 401


def test_anonymous_cannot_vote_on_a_post(client, second_client):
    post, _ = _seed_post(client, second_client)
    response = anonymous().post(f"/posts/{post['id']}/vote", json={"value": 1})
    assert response.status_code == 401


def test_anonymous_cannot_create_a_comment(client, second_client):
    post, _ = _seed_post(client, second_client)
    response = anonymous().post(f"/posts/{post['id']}/comments", json={"body": "hi"})
    assert response.status_code == 401


def test_anonymous_cannot_search_users(client):
    response = client.get("/users/search?q=bob")
    assert response.status_code == 401


def test_anonymous_cannot_discover_users(client):
    response = client.get("/users/discover")
    assert response.status_code == 401


def test_anonymous_cannot_list_own_friends(client):
    response = client.get("/friends")
    assert response.status_code == 401


def test_anonymous_cannot_list_friend_requests(client):
    response = client.get("/friends/requests")
    assert response.status_code == 401


def test_anonymous_cannot_send_a_friend_request(client, second_client):
    register_and_login(second_client, "bob", "bob@example.com")
    response = client.post("/friends/requests/bob")
    assert response.status_code == 401


def test_logged_in_user_can_still_send_and_accept_friend_requests(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    sent = client.post("/friends/requests/bob")
    assert sent.status_code == 201
    request_id = next(
        item["id"] for item in second_client.get("/friends/requests").json()
        if item["sender_username"] == "alice"
    )
    accepted = second_client.post(f"/friends/requests/{request_id}/accept")
    assert accepted.status_code == 200
    assert client.get("/friends").json()[0]["username"] == "bob"


def test_public_friends_list_stays_guest_viewable_as_part_of_the_profile_page(client, second_client):
    """routers/social.py's public_friends is deliberately NOT part of this
    gating: it backs the public profile page (routes/users/[username]),
    the same feature as profiles.py's public_profile/public_music_identity/
    public_user_mixes, none of which require auth either. Only the
    Community feed and social-graph-management surface is gated."""

    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    client.post("/friends/requests/bob")
    request_id = next(
        item["id"] for item in second_client.get("/friends/requests").json()
        if item["sender_username"] == "alice"
    )
    second_client.post(f"/friends/requests/{request_id}/accept")

    response = anonymous().get("/users/alice/friends")
    assert response.status_code == 200
    assert response.json()[0]["username"] == "bob"
