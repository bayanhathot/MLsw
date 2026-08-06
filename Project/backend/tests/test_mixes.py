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


def test_start_mix_builds_segment_queue(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.mixes.search_tracks",
        lambda prompt, limit=5: sample_tracks(),
    )

    response = client.post(
        "/mixes/start",
        json={"prompt": "energetic electronic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"].startswith("mix_")
    assert body["prompt"] == "energetic electronic"
    assert len(body["segments"]) == 2
    assert body["segments"][0]["end_second"] == 45
    assert body["segments"][1]["end_second"] == 30


def test_start_mix_returns_404_when_provider_has_no_tracks(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.mixes.search_tracks",
        lambda prompt, limit=5: [],
    )

    response = client.post("/mixes/start", json={"prompt": "unknown mood"})

    assert response.status_code == 404
    assert response.json()["detail"] == "No tracks found for this prompt"
