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
    ]


def create_post(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.mix_service.search_tracks",
        lambda prompt, limit=5: sample_tracks(),
    )

    return client.post("/posts", json={"prompt": "chill", "description": "d"})


def test_play_event_requires_authentication(client):
    response = client.post(
        "/play-events",
        json={"mix_id": 1, "segment_id": 1, "seconds_listened": 10, "event_type": "heartbeat"},
    )

    assert response.status_code == 401


def test_play_event_records_and_returns_id(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    post = create_post(client, monkeypatch).json()
    mix_id = post["mix"]["id"]
    segment_id = post["mix"]["segments"][0]["id"]

    response = client.post(
        "/play-events",
        json={
            "mix_id": mix_id,
            "segment_id": segment_id,
            "seconds_listened": 12,
            "event_type": "heartbeat",
        },
    )

    assert response.status_code == 201
    assert response.json()["seconds_listened"] == 12


def test_play_event_clamps_oversized_seconds(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    post = create_post(client, monkeypatch).json()
    mix_id = post["mix"]["id"]
    segment_id = post["mix"]["segments"][0]["id"]

    response = client.post(
        "/play-events",
        json={
            "mix_id": mix_id,
            "segment_id": segment_id,
            "seconds_listened": 60,
            "event_type": "heartbeat",
        },
    )

    assert response.status_code == 201
    assert response.json()["seconds_listened"] == 25


def test_play_event_rejects_segment_not_in_mix(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    post = create_post(client, monkeypatch).json()
    mix_id = post["mix"]["id"]
    real_segment_id = post["mix"]["segments"][0]["id"]

    response = client.post(
        "/play-events",
        json={
            "mix_id": mix_id + 999,
            "segment_id": real_segment_id,
            "seconds_listened": 10,
            "event_type": "heartbeat",
        },
    )

    assert response.status_code == 404


def test_play_event_rejects_invalid_event_type(client, monkeypatch):
    register_and_login(client, "alice", "alice@example.com")

    post = create_post(client, monkeypatch).json()
    mix_id = post["mix"]["id"]
    segment_id = post["mix"]["segments"][0]["id"]

    response = client.post(
        "/play-events",
        json={
            "mix_id": mix_id,
            "segment_id": segment_id,
            "seconds_listened": 10,
            "event_type": "click",
        },
    )

    assert response.status_code == 422
