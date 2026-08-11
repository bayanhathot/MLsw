from conftest import register_and_login


def sample_tracks():
    return [
        {
            "title": "Track One",
            "artist": "Artist",
            "audio_url": "https://audio.example/1",
            "cover_url": None,
            "duration": 120,
            "source": "audius",
            "source_track_id": "one",
        },
        {
            "title": "Short",
            "artist": "Artist",
            "audio_url": "https://audio.example/2",
            "cover_url": None,
            "duration": 20,
            "source": "audius",
            "source_track_id": "two",
        },
    ]


def test_mix_persists_and_provider_empty_uses_safe_fallback(client, monkeypatch):
    monkeypatch.setattr("app.services.mix_service.search_tracks", lambda prompt, limit=5: [])
    response = client.post("/mixes/start", json={"prompt": "unknown mood"})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"].startswith("mix_")
    assert body["segments"][0]["source"] == "local-demo"
    assert body["segments"][0]["audio_url"] == "/api/static/audio/zonix-demo.wav"


def test_mix_feed_library_like_and_save(client, second_client, monkeypatch):
    monkeypatch.setattr("app.services.mix_service.search_tracks", lambda prompt, limit=5: sample_tracks())
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert len(mix["segments"]) == 2
    assert mix["segments"][0]["end_second"] == 45
    assert mix["segments"][1]["end_second"] == 20
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 200

    assert second_client.post(f"/mixes/{mix['id']}/like").json()["like_count"] == 1
    assert second_client.post(f"/mixes/{mix['id']}/like").json()["like_count"] == 1
    assert second_client.post(f"/mixes/{mix['id']}/save").status_code == 200
    feed = second_client.get("/mixes/feed").json()
    assert feed[0]["is_liked"] is True
    assert feed[0]["is_saved"] is True
    library = second_client.get("/mixes/library").json()
    assert library["owned"] == []
    assert library["saved"][0]["id"] == mix["id"]
    assert second_client.delete(f"/mixes/{mix['id']}/like").json()["like_count"] == 0
    assert second_client.delete(f"/mixes/{mix['id']}/save").json()["is_saved"] is False
