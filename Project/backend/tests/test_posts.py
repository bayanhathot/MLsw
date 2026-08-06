def register_and_login(client, username, email, password="strongpassword"):
    client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def become_friends(client_a, client_b, username_a, username_b):
    request_id = client_a.post(
        "/friends/requests", json={"addressee_username": username_b}
    ).json()["id"]
    client_b.post(f"/friends/requests/{request_id}/accept")


def sample_tracks():
    return [
        {
            "title": "Long Track",
            "artist": "Artist One",
            "audio_url": "https://audio.example/long",
            "cover_url": None,
            "duration": 180,
            "source": "audius",
            "source_track_id": "track-1",
        },
        {
            "title": "Short Track",
            "artist": "Artist Two",
            "audio_url": "https://audio.example/short",
            "cover_url": "https://images.example/short",
            "duration": 30,
            "source": "audius",
            "source_track_id": "track-2",
        },
    ]


def create_post(client, monkeypatch, prompt="energetic electronic", description="my new mix"):
    monkeypatch.setattr(
        "app.services.mix_service.search_tracks",
        lambda prompt, limit=5: sample_tracks(),
    )

    return client.post("/posts", json={"prompt": prompt, "description": description})


def test_create_post_builds_mix_and_persists(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    response = create_post(client, monkeypatch)

    assert response.status_code == 201
    body = response.json()
    assert body["description"] == "my new mix"
    assert body["author_username"] == "alice"
    assert body["like_count"] == 0
    assert body["comment_count"] == 0
    assert body["share_count"] == 0
    assert body["liked_by_me"] is False
    assert len(body["mix"]["segments"]) == 2
    assert body["mix"]["segments"][0]["end_second"] == 45
    assert body["mix"]["segments"][1]["end_second"] == 30


def test_create_post_returns_404_when_no_tracks(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    monkeypatch.setattr(
        "app.services.mix_service.search_tracks",
        lambda prompt, limit=5: [],
    )

    response = client.post("/posts", json={"prompt": "unknown mood", "description": "x"})

    assert response.status_code == 404


def test_feed_shows_own_and_friends_posts_only(client, second_client, third_client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    register_and_login(third_client, "carol", "carol@example.com")

    become_friends(client, second_client, "alice", "bob")

    create_post(client, monkeypatch, description="alice's mix")
    create_post(second_client, monkeypatch, description="bob's mix")
    create_post(third_client, monkeypatch, description="carol's mix")

    feed = client.get("/posts/feed").json()
    descriptions = {post["description"] for post in feed}

    assert descriptions == {"alice's mix", "bob's mix"}


def test_feed_requires_authentication(client):
    response = client.get("/posts/feed")

    assert response.status_code == 401


def test_like_and_unlike_post(client, second_client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    post_id = create_post(client, monkeypatch).json()["id"]

    like_response = second_client.post(f"/posts/{post_id}/like")
    assert like_response.status_code == 200
    assert like_response.json()["like_count"] == 1
    assert like_response.json()["liked_by_me"] is True

    # Liking again is idempotent.
    again = second_client.post(f"/posts/{post_id}/like")
    assert again.json()["like_count"] == 1

    unlike_response = second_client.delete(f"/posts/{post_id}/like")
    assert unlike_response.json()["like_count"] == 0
    assert unlike_response.json()["liked_by_me"] is False


def test_comment_create_list_and_delete(client, second_client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    post_id = create_post(client, monkeypatch).json()["id"]

    comment_response = second_client.post(
        f"/posts/{post_id}/comments", json={"body": "love this vibe"}
    )
    assert comment_response.status_code == 201
    comment = comment_response.json()
    assert comment["author_username"] == "bob"
    assert comment["body"] == "love this vibe"

    listed = client.get(f"/posts/{post_id}/comments").json()
    assert len(listed) == 1

    forbidden = client.delete(f"/posts/{post_id}/comments/{comment['id']}")
    assert forbidden.status_code == 403

    allowed = second_client.delete(f"/posts/{post_id}/comments/{comment['id']}")
    assert allowed.status_code == 204

    assert client.get(f"/posts/{post_id}/comments").json() == []


def test_share_dedupes_per_user(client, second_client, third_client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    register_and_login(third_client, "carol", "carol@example.com")

    post_id = create_post(client, monkeypatch).json()["id"]

    first = second_client.post(f"/posts/{post_id}/share")
    assert first.json()["share_count"] == 1

    again = second_client.post(f"/posts/{post_id}/share")
    assert again.json()["share_count"] == 1

    third = third_client.post(f"/posts/{post_id}/share")
    assert third.json()["share_count"] == 2


def test_delete_post_requires_author(client, second_client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    post_id = create_post(client, monkeypatch).json()["id"]

    forbidden = second_client.delete(f"/posts/{post_id}")
    assert forbidden.status_code == 403

    allowed = client.delete(f"/posts/{post_id}")
    assert allowed.status_code == 204

    assert client.get(f"/posts/{post_id}").status_code == 404


def test_user_posts_endpoint_returns_only_that_users_posts(client, second_client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")

    create_post(client, monkeypatch, description="alice's mix")
    create_post(second_client, monkeypatch, description="bob's mix")

    alice_posts = client.get("/users/alice/posts").json()

    assert len(alice_posts) == 1
    assert alice_posts[0]["description"] == "alice's mix"
