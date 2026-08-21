from pathlib import Path
from time import monotonic, sleep

from conftest import register_and_login

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.database.models.mix import Mix
from app.services import studio_service, upload_queue
from app.services.pipeline.audio_renderer import PydubAudioRenderer

DEMO_WAV = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "static"
    / "audio"
    / "cuemix-demo.wav"
)


def _catalog_track(db_session, owner_id, *, title="Studio Source"):
    storage_name = f"{title.casefold().replace(' ', '-')}.wav"
    directory = upload_queue.UPLOAD_DIR / "catalog"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / storage_name).write_bytes(DEMO_WAV.read_bytes())
    row = CatalogTrack(
        owner_id=owner_id,
        visibility="private",
        title=title,
        artist="Studio Artist",
        album="Studio Album",
        genre="Electronic",
        vibe_label="energetic",
        storage_name=storage_name,
        content_type="audio/wav",
        duration_seconds=60,
        analysis_status="completed",
        bpm=120,
        bpm_confidence=0.9,
        musical_key="C",
        key_mode="major",
        camelot="8B",
        key_confidence=0.8,
        segment_start_second=10,
        segment_end_second=40,
        segment_method="chorus_detection",
        phrase_boundaries_json=[0.0, 16.0, 32.0, 48.0],
        analysis_version="v3",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _save(client, track_id, start_ms, end_ms, label):
    response = client.post(
        "/studio/segments",
        json={
            "source_type": "catalog",
            "source_track_id": str(track_id),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "label": label,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_saved_segment_persists_validates_bounds_and_enforces_ownership(
    client, second_client, db_session
):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])

    search = client.get("/studio/tracks/search?q=Studio Source")
    assert search.status_code == 200
    assert search.json()[0]["suggested_start_ms"] == 10_000

    saved = _save(client, track.id, 1234, 5432, "Exact hook")
    assert saved["start_ms"] == 1234
    assert saved["end_ms"] == 5432
    assert client.get("/studio/segments").json()[0]["id"] == saved["id"]

    invalid = client.post(
        "/studio/segments",
        json={
            "source_type": "catalog",
            "source_track_id": str(track.id),
            "start_ms": 59_500,
            "end_ms": 61_000,
            "label": "Out of range",
        },
    )
    assert invalid.status_code == 422

    register_and_login(second_client, "bob", "bob@example.com")
    assert second_client.patch(
        f"/studio/segments/{saved['id']}", json={"label": "stolen"}
    ).status_code == 404
    assert second_client.delete(f"/studio/segments/{saved['id']}").status_code == 404

    # A fresh authenticated request sees the persisted row, matching the
    # logout/login/restart persistence contract rather than browser storage.
    assert client.post("/auth/logout").status_code == 200
    assert client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "strongpass"}
    ).status_code == 200
    assert client.get(f"/studio/segments/{saved['id']}").json()["label"] == "Exact hook"


def test_studio_draft_snapshots_reorder_and_optimistic_revision(client, db_session):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    saved = [
        _save(client, track.id, 1000, 5000, "One"),
        _save(client, track.id, 6000, 10_000, "Two"),
        _save(client, track.id, 11_000, 15_000, "Three"),
    ]
    mix = client.post("/studio/mixes", json={"title": "Manual three"}).json()
    for segment in saved:
        response = client.post(
            f"/studio/mixes/{mix['id']}/items",
            json={"saved_segment_id": segment["id"], "expected_revision": mix["revision"]},
        )
        assert response.status_code == 200, response.text
        mix = response.json()

    original_bounds = [
        (item["source_start_ms"], item["source_end_ms"]) for item in mix["segments"]
    ]
    assert client.patch(
        f"/studio/segments/{saved[0]['id']}",
        json={"start_ms": 2000, "end_ms": 5500},
    ).status_code == 200
    restored = client.get(f"/studio/mixes/{mix['id']}").json()
    assert [
        (item["source_start_ms"], item["source_end_ms"])
        for item in restored["segments"]
    ] == original_bounds

    reversed_ids = [item["id"] for item in reversed(restored["segments"])]
    reordered = client.put(
        f"/studio/mixes/{mix['id']}/items/reorder",
        json={"segment_ids": reversed_ids, "expected_revision": restored["revision"]},
    )
    assert reordered.status_code == 200, reordered.text
    assert [item["id"] for item in reordered.json()["segments"]] == reversed_ids

    stale = client.patch(
        f"/studio/mixes/{mix['id']}",
        json={"title": "stale", "expected_revision": restored["revision"]},
    )
    assert stale.status_code == 409


def test_transition_preview_render_publish_and_immutable_duplicate(
    client, db_session, monkeypatch
):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    first = _save(client, track.id, 1000, 5000, "First")
    second = _save(client, track.id, 6000, 10_000, "Second")
    mix = client.post("/studio/mixes", json={"title": "Render me"}).json()
    for saved in (first, second):
        mix = client.post(
            f"/studio/mixes/{mix['id']}/items",
            json={"saved_segment_id": saved["id"], "expected_revision": mix["revision"]},
        ).json()

    item = mix["segments"][0]
    changed = client.patch(
        f"/studio/mixes/{mix['id']}/items/{item['id']}/transition",
        json={
            "expected_revision": mix["revision"],
            "transition_type": "fade_in_out",
            "duration_ms": 1200,
        },
    )
    assert changed.status_code == 200, changed.text
    mix = changed.json()
    assert mix["segments"][0]["compatibility_score"] is not None

    preview = client.post(
        f"/studio/mixes/{mix['id']}/items/{item['id']}/transition-preview"
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["audio_url"].endswith(".wav")

    # The suite's StaticPool intentionally shares one in-memory SQLite
    # connection across threads, which cannot model the production worker's
    # independent Postgres session reliably. Keep the queue boundary real but
    # execute its callback inline here; Docker smoke coverage exercises the
    # actual background worker against Postgres.
    def render_inline(mix_id, owner_id, revision, priority=4):
        del priority
        row = studio_service.owned_studio_mix(db_session, owner_id, mix_id)
        studio_service.render_mix(
            db_session,
            row,
            PydubAudioRenderer(),
            expected_revision=revision,
        )

    monkeypatch.setattr(upload_queue.upload_queue, "submit_studio_render", render_inline)

    rendered = client.post(f"/studio/mixes/{mix['id']}/render")
    assert rendered.status_code == 200, rendered.text
    mix = rendered.json()
    deadline = monotonic() + 5
    while mix["render_status"] == "rendering" and monotonic() < deadline:
        sleep(0.05)
        mix = client.get(f"/studio/mixes/{mix['id']}").json()
    assert mix["render_status"] == "ready"
    assert mix["rendered_revision"] == mix["revision"]
    assert len({item["audio_url"] for item in mix["segments"]}) == 1

    published = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert client.patch(
        f"/mixes/{mix['id']}",
        json={"title": "legacy bypass", "description": None, "cover_url": None},
    ).status_code == 409
    assert client.post(f"/mixes/{mix['id']}/publish").status_code == 409
    assert client.patch(
        f"/studio/mixes/{mix['id']}",
        json={"title": "mutated", "expected_revision": mix["revision"]},
    ).status_code == 409
    duplicate = client.post(f"/studio/mixes/{mix['id']}/duplicate")
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "draft"
    assert duplicate.json()["segments"][0]["source_start_ms"] == first["start_ms"]


def test_passive_signals_are_bounded_and_auto_mix_stays_editable(client, db_session):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    first = _save(client, track.id, 1000, 5000, "Positive")
    second = _save(client, track.id, 6000, 10_000, "Skipped")
    for _ in range(30):
        assert client.post(
            "/studio/behavior",
            json={"event_type": "segment_replay", "saved_segment_id": first["id"]},
        ).status_code == 201
        assert client.post(
            "/studio/behavior",
            json={"event_type": "early_skip", "saved_segment_id": second["id"]},
        ).status_code == 201

    signals = {row["saved_segment_id"]: row for row in client.get("/studio/behavior/signals").json()}
    assert signals[first["id"]]["total_adjustment"] <= 0.35
    assert signals[second["id"]]["total_adjustment"] >= -0.25
    assert signals[first["id"]]["total_adjustment"] > signals[second["id"]]["total_adjustment"]

    auto = client.post(
        "/studio/auto-mix",
        json={"title": "Saved workout", "prompt": "gym", "mode": "workout", "limit": 2},
    )
    assert auto.status_code == 200, auto.text
    body = auto.json()
    assert body["mode"] == "workout"
    assert body["is_studio"] is True
    assert body["status"] == "draft"
    assert body["segments"][0]["saved_segment_id"] == first["id"]
    assert client.patch(
        f"/studio/mixes/{body['id']}",
        json={"title": "Edited auto mix", "expected_revision": body["revision"]},
    ).status_code == 200


def test_audius_segments_are_editable_but_provider_audio_cannot_be_published(
    client, db_session, monkeypatch
):
    register_and_login(client)
    external = ExternalTrack(
        source="audius",
        external_id="remote-1",
        title="Remote track",
        artist="Remote artist",
        duration_sec=90,
        analysis_status="completed",
        analysis_attempt_count=1,
        segment_start_second=15,
        segment_end_second=45,
        segment_method="chorus_detection",
    )
    db_session.add(external)
    db_session.commit()
    monkeypatch.setattr(
        "app.services.studio_service.audio_renderer.validate_selected_segment",
        lambda _selected: (True, None),
    )

    saved = client.post(
        "/studio/segments",
        json={
            "source_type": "audius",
            "source_track_id": "remote-1",
            "start_ms": 15_250,
            "end_ms": 45_750,
            "label": "Provider hook",
        },
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["start_ms"] == 15_250
    mix = client.post("/studio/mixes", json={"title": "Private provider draft"}).json()
    mix = client.post(
        f"/studio/mixes/{mix['id']}/items",
        json={
            "saved_segment_id": saved.json()["id"],
            "expected_revision": mix["revision"],
        },
    ).json()
    row = db_session.get(Mix, mix["id"])
    row.render_status = "ready"
    row.rendered_revision = row.revision
    row.rendered_audio_url = "/static/audio/private.wav"
    db_session.commit()

    blocked = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert blocked.status_code == 422
    assert "Provider-sourced" in blocked.json()["detail"]


def test_studio_assistant_fails_open_and_validates_grounded_bounds(
    client, db_session, monkeypatch
):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    saved = _save(client, track.id, 1000, 5000, "Assistant target")
    monkeypatch.delenv("STUDIO_AI_URL", raising=False)
    request = {
        "messages": [{"role": "user", "content": "Keep the vocal phrase"}],
        "active_saved_segment_id": saved["id"],
    }
    unavailable = client.post("/studio/assistant/chat", json=request)
    assert unavailable.status_code == 200
    assert unavailable.json()["available"] is False

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "recommendation_type": "segment_bounds",
                "candidate_id": saved["id"],
                "proposed_start_ms": 1200,
                "proposed_end_ms": 4800,
                "proposed_order": None,
                "transition_change": None,
                "reason_tags": ["phrase"],
                "explanation": "A grounded alternative.",
                "confidence": 0.8,
                "requires_user_confirmation": True,
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setenv("STUDIO_AI_URL", "http://studio-ai-service:8001")
    monkeypatch.setattr("app.services.studio_ai_client.httpx.Client", Client)
    grounded = client.post("/studio/assistant/chat", json=request)
    assert grounded.status_code == 200
    assert grounded.json()["available"] is True
    assert grounded.json()["recommendation"]["candidate_id"] == saved["id"]

    monkeypatch.setattr(
        Response,
        "json",
        lambda _self: {
            "recommendation_type": "segment_bounds",
            "candidate_id": saved["id"],
            "proposed_start_ms": 1200,
            "proposed_end_ms": 600_001,
            "proposed_order": None,
            "transition_change": None,
            "reason_tags": ["unsafe"],
            "explanation": "An invalid out-of-range suggestion.",
            "confidence": 0.8,
            "requires_user_confirmation": True,
        },
    )
    rejected = client.post("/studio/assistant/chat", json=request)
    assert rejected.status_code == 200
    assert rejected.json()["available"] is False
