def register_and_login(client, username, email, password="strongpassword"):
    client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


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


def test_get_profile_creates_default_on_first_access(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.get("/users/me/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["theme_preference"] == "dark"
    assert body["display_name"] is None
    assert body["bio"] is None
    assert body["favorite_genres"] is None


def test_update_profile_only_changes_provided_fields(client):
    register_and_login(client, "alice", "alice@example.com")

    client.patch("/users/me/profile", json={"display_name": "Alice A."})

    response = client.patch("/users/me/profile", json={"bio": "I love lofi."})

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Alice A."
    assert body["bio"] == "I love lofi."


def test_update_profile_rejects_invalid_theme(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.patch("/users/me/profile", json={"theme_preference": "neon"})

    assert response.status_code == 422


def test_update_profile_accepts_favorite_genres_list(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.patch(
        "/users/me/profile", json={"favorite_genres": ["lofi", "house"]}
    )

    assert response.status_code == 200
    assert response.json()["favorite_genres"] == ["lofi", "house"]


def test_stats_for_user_with_no_listening_history(client):
    register_and_login(client, "alice", "alice@example.com")

    response = client.get("/users/alice/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["minutes_listened"] == 0
    assert body["favorite_artists"] == []


def test_stats_aggregate_from_play_events(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    post = create_post(client, monkeypatch).json()
    mix_id = post["mix"]["id"]
    segments = post["mix"]["segments"]

    # Listen to segment 0 (Artist One) for 20s twice, and segment 1
    # (Artist Two) for 10s once.
    client.post(
        "/play-events",
        json={
            "mix_id": mix_id,
            "segment_id": segments[0]["id"],
            "seconds_listened": 20,
            "event_type": "heartbeat",
        },
    )
    client.post(
        "/play-events",
        json={
            "mix_id": mix_id,
            "segment_id": segments[0]["id"],
            "seconds_listened": 20,
            "event_type": "heartbeat",
        },
    )
    client.post(
        "/play-events",
        json={
            "mix_id": mix_id,
            "segment_id": segments[1]["id"],
            "seconds_listened": 10,
            "event_type": "pause",
        },
    )

    response = client.get("/users/alice/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["minutes_listened"] == 0  # 50 seconds total, rounds down to 0 minutes
    assert body["favorite_artists"][0] == {"artist": "Artist One", "seconds_listened": 40}
    assert body["favorite_artists"][1] == {"artist": "Artist Two", "seconds_listened": 10}
