from pathlib import Path

from conftest import register_and_login

from app.database.models.catalog import CatalogTrack
from app.services import upload_queue
from app.services.pipeline.catalog_retriever import _ensure_seed_catalog

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
        "app.services.pipeline.audio_renderer._download",
        lambda url: (_DEMO_WAV_BYTES, None),
    )


def test_mix_persists_and_provider_empty_uses_safe_fallback(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: [],
    )
    response = client.post("/mixes/start", json={"prompt": "unknown mood"})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"].startswith("mix_")
    # Audius came back empty, so mix_service fell back to the real catalog
    # (mood-bucket matched), not a single hardcoded local-demo dict anymore.
    assert body["segments"][0]["source"] == "catalog"
    assert body["segments"][0]["audio_url"].startswith("/api/media/renders/")


def test_named_auto_mix_mode_is_applied_and_persisted(client, monkeypatch, db_session):
    _patch_audius(monkeypatch, sample_tracks())
    response = client.post(
        "/mixes/start",
        json={"prompt": "quiet ambient background", "mode": "party"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "party"
    from app.database.models.mix import Mix

    row = db_session.get(Mix, body["id"])
    assert row.mode == "party"


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
    assert first["track_duration_seconds"] == 120
    assert second["track_duration_seconds"] == 20
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
    mix_like_notices = [
        item
        for item in client.get("/notifications").json()
        if item["kind"] == "mix_like"
    ]
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


def test_channel_hub_receives_user_notification_on_mix_like(
    client, second_client, monkeypatch
):
    """mixes.py publishes a mix-like notification onto channel_hub's
    "user:{id}" channel (see channel_hub.py)."""

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


def test_mine_and_saved_endpoints_return_the_correct_library_subsets(
    client, second_client, monkeypatch
):
    _patch_audius(monkeypatch, sample_tracks())
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 200
    assert second_client.post(f"/mixes/{mix['id']}/save").status_code == 200

    assert [item["id"] for item in client.get("/mixes/mine").json()] == [mix["id"]]
    assert client.get("/mixes/saved").json() == []
    assert second_client.get("/mixes/mine").json() == []
    assert [item["id"] for item in second_client.get("/mixes/saved").json()] == [
        mix["id"]
    ]


def test_named_artist_with_no_audius_or_catalog_match_still_falls_back_safely(
    client, monkeypatch
):
    """Mixes must never hard-fail the way a session can plainly report "no
    match": even a named artist with nothing anywhere still yields a mix."""

    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: [],
    )
    response = client.post(
        "/mixes/start", json={"prompt": "play something by Zzzqx Nonexistent Artist"}
    )
    assert response.status_code == 200
    assert response.json()["segments"]


def test_mix_can_use_the_owners_own_private_catalog_track(
    client, monkeypatch, db_session
):
    """create_mix() threads owner_id into viewer_id (mirroring
    session_manager.py's identical viewer_id=user_id pattern), so a
    signed-in owner's own private catalog upload is eligible for their own
    mix -- not just public tracks, same as it already is for their own
    session."""

    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: [],
    )
    user = register_and_login(client, "priv_mix_owner", "priv_mix_owner@example.com")

    storage_name = "owner-private-mix-track.wav"
    catalog_dir = upload_queue.UPLOAD_DIR / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / storage_name).write_bytes(_DEMO_WAV_BYTES)
    db_session.add(
        CatalogTrack(
            owner_id=user["id"],
            title="Owner Private Mix Track",
            artist="Zzq Mix Private Artist",
            visibility="private",
            storage_name=storage_name,
            content_type="audio/wav",
        )
    )
    db_session.commit()

    mix = client.post(
        "/mixes/start", json={"prompt": "play something by Zzq Mix Private Artist"}
    ).json()
    assert mix["segments"]
    assert mix["segments"][0]["title"] == "Owner Private Mix Track"


def test_mix_excludes_another_users_private_catalog_track(
    client, second_client, monkeypatch, db_session
):
    """The other half of the same fix: viewer_id must scope to *this*
    mix's own owner, never let a different user's private upload leak in."""

    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: [],
    )
    owner = register_and_login(client, "priv_mix_owner2", "priv_mix_owner2@example.com")
    register_and_login(
        second_client, "other_mix_viewer", "other_mix_viewer@example.com"
    )
    # Seed the public demo catalog *before* adding the private row below --
    # _ensure_seed_catalog only self-heals an empty table, and this test
    # needs a real public fallback for the last-resort tier to land on
    # once the private track (correctly) isn't a candidate for this viewer.
    _ensure_seed_catalog(db_session)
    db_session.add(
        CatalogTrack(
            owner_id=owner["id"],
            title="Owner Private Mix Track Two",
            artist="Zzq Mix Private Artist Two",
            visibility="private",
            storage_name="x.wav",
            content_type="audio/wav",
        )
    )
    db_session.commit()

    # Never hard-fails (mixes' own guarantee, see the "not even the catalog
    # or Audius" test above) -- but the private track must never be the one
    # used for a session that isn't its owner's.
    mix = second_client.post(
        "/mixes/start", json={"prompt": "play something by Zzq Mix Private Artist Two"}
    ).json()
    assert mix["segments"]
    assert mix["segments"][0]["title"] != "Owner Private Mix Track Two"
