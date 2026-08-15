from pathlib import Path

from conftest import register_and_login

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
).read_bytes()


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


def _patch_audius(monkeypatch, tracks):
    """Both the retrieval step and AudioRenderer's remote download are
    patched, so mixes with Audius candidates render a real (deterministic,
    network-free) composite instead of degrading to a pass-through because
    the fake example.test URLs aren't reachable."""

    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download", lambda url: (_DEMO_WAV_BYTES, None)
    )


def test_mix_persists_and_provider_empty_uses_safe_fallback(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks", lambda prompt, limit=5: []
    )
    response = client.post("/mixes/start", json={"prompt": "unknown mood"})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"].startswith("mix_")
    # Audius came back empty, so mix_service fell back to the real catalog
    # (mood-bucket matched), not a single hardcoded local-demo dict anymore.
    assert body["segments"][0]["source"] == "catalog"
    assert body["segments"][0]["audio_url"].startswith("/api/media/renders/")


def test_mix_renders_a_real_crossfaded_composite_across_tracks(client, monkeypatch):
    _patch_audius(monkeypatch, sample_tracks())
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert len(mix["segments"]) == 2
    first, second = mix["segments"]
    # Both segments point at the same rendered composite file, not their
    # original per-track URLs -- a real crossfade actually happened.
    assert first["audio_url"] == second["audio_url"]
    assert first["audio_url"].startswith("/api/media/renders/")
    assert first["audio_url"].endswith(".wav")
    assert first["end_second"] > first["start_second"]
    assert second["end_second"] > second["start_second"]
    assert first["transition_to_next"] == "crossfade"
    assert second["transition_to_next"] == "end"


def test_mix_feed_library_like_and_save(client, second_client, monkeypatch):
    _patch_audius(monkeypatch, sample_tracks())
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert len(mix["segments"]) == 2
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 200

    assert second_client.post(f"/mixes/{mix['id']}/like").json()["like_count"] == 1
    assert second_client.post(f"/mixes/{mix['id']}/like").json()["like_count"] == 1
    mix_like_notices = [item for item in client.get("/notifications").json() if item["kind"] == "mix_like"]
    assert len(mix_like_notices) == 1
    assert second_client.post(f"/mixes/{mix['id']}/save").status_code == 200
    feed = second_client.get("/mixes/feed").json()
    assert feed[0]["is_liked"] is True
    assert feed[0]["is_saved"] is True
    library = second_client.get("/mixes/library").json()
    assert library["owned"] == []
    assert library["saved"][0]["id"] == mix["id"]
    assert second_client.delete(f"/mixes/{mix['id']}/like").json()["like_count"] == 0
    assert second_client.delete(f"/mixes/{mix['id']}/save").json()["is_saved"] is False


def test_channel_hub_receives_user_notification_on_mix_like(client, second_client, monkeypatch):
    """mixes.py keeps notification_hub.publish's existing shape but now also
    mirrors it onto channel_hub's "user:{id}" channel (see channel_hub.py)."""

    from unittest.mock import AsyncMock

    _patch_audius(monkeypatch, sample_tracks())
    publish = AsyncMock()
    monkeypatch.setattr("app.routers.mixes.channel_hub.publish", publish)
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 200
    alice_id = client.get("/auth/me").json()["id"]

    assert second_client.post(f"/mixes/{mix['id']}/like").json()["like_count"] == 1

    channel, event_type, data = publish.await_args.args
    assert channel == f"user:{alice_id}"
    assert event_type == "notification"
    assert data["kind"] == "mix_like"


def test_blocked_owner_hides_direct_mix_access(client, second_client, monkeypatch):
    _patch_audius(monkeypatch, sample_tracks())
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 200

    assert second_client.get(f"/mixes/{mix['id']}").status_code == 200
    assert second_client.post("/users/alice/block").status_code == 204
    assert second_client.get(f"/mixes/{mix['id']}").status_code == 404


def test_mine_and_saved_endpoints_return_the_correct_library_subsets(client, second_client, monkeypatch):
    _patch_audius(monkeypatch, sample_tracks())
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 200
    assert second_client.post(f"/mixes/{mix['id']}/save").status_code == 200

    assert [item["id"] for item in client.get("/mixes/mine").json()] == [mix["id"]]
    assert client.get("/mixes/saved").json() == []
    assert second_client.get("/mixes/mine").json() == []
    assert [item["id"] for item in second_client.get("/mixes/saved").json()] == [mix["id"]]


def test_named_artist_with_no_audius_or_catalog_match_still_falls_back_safely(client, monkeypatch):
    """Mixes must never hard-fail the way a session can plainly report "no
    match": even a named artist with nothing anywhere still yields a mix."""

    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks", lambda prompt, limit=5: []
    )
    response = client.post(
        "/mixes/start", json={"prompt": "play something by Zzzqx Nonexistent Artist"}
    )
    assert response.status_code == 200
    assert response.json()["segments"]
