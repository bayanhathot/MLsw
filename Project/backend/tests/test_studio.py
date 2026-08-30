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
    assert search.json()[0]["phrase_boundaries_ms"] == [0, 16_000, 32_000, 48_000]
    assert search.json()[0]["min_segment_ms"] == studio_service.MIN_SEGMENT_MS
    assert search.json()[0]["max_segment_ms"] == studio_service.MAX_SEGMENT_MS

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
    published_body = published.json()
    assert published_body["status"] == "published"
    # Creator-owned hosted (catalog) audio uses the rendered_asset mode,
    # and its composite file is promoted out of the temporary-render
    # directory the TTL sweep scans -- see
    # audio_renderer.promote_render_to_published.
    assert published_body["publication_mode"] == "rendered_asset"
    assert published_body["published_audio_url"]
    assert "/media/renders/published/" in published_body["published_audio_url"]
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


def test_studio_mix_with_audius_segments_publishes_as_provider_manifest(
    client, db_session, monkeypatch
):
    """Publishing a Studio mix containing Audius segments succeeds -- it
    must never permanently republish the rendered composite WAV as public
    audio (see SECURITY.md); it publishes an immutable provider_manifest
    instead, and the same segment stays streamable straight from Audius via
    the public playback-manifest endpoint."""

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
    mix = client.post("/studio/mixes", json={"title": "Provider draft"}).json()
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
    row.rendered_audio_url = "/media/renders/temporary-composite.wav"
    db_session.commit()

    published = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "published"
    assert body["publication_mode"] == "provider_manifest"
    # The temporary composite render must never become the permanent
    # public audio for a provider-sourced publish.
    assert body["published_audio_url"] is None

    manifest = client.get(f"/mixes/{mix['id']}/playback-manifest")
    assert manifest.status_code == 200, manifest.text
    manifest_body = manifest.json()
    assert manifest_body["mode"] == "provider_manifest"
    assert len(manifest_body["segments"]) == 1
    segment = manifest_body["segments"][0]
    assert segment["availability"] == "available"
    assert segment["source"] == "audius"
    assert segment["audio_url"] and segment["audio_url"].startswith("https://discoveryprovider")
    assert segment["attribution"]
    assert segment["rights_status"] == "provider_streaming"


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
                "recommendation_type": "plan",
                "base_revision": None,
                "remembered_constraints": ["Keep the vocal phrase"],
                "proposed_order": None,
                "transition_changes": [],
                "segment_bound_change": {
                    "candidate_id": saved["id"],
                    "proposed_start_ms": 1200,
                    "proposed_end_ms": 4800,
                },
                "calculations": None,
                "warnings": [],
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
    assert (
        grounded.json()["recommendation"]["segment_bound_change"]["candidate_id"]
        == saved["id"]
    )

    monkeypatch.setattr(
        Response,
        "json",
        lambda _self: {
            "recommendation_type": "plan",
            "base_revision": None,
            "remembered_constraints": [],
            "proposed_order": None,
            "transition_changes": [],
            "segment_bound_change": {
                "candidate_id": saved["id"],
                "proposed_start_ms": 1200,
                "proposed_end_ms": 600_001,
            },
            "calculations": None,
            "warnings": [],
            "reason_tags": ["unsafe"],
            "explanation": "An invalid out-of-range suggestion.",
            "confidence": 0.8,
            "requires_user_confirmation": True,
        },
    )
    rejected = client.post("/studio/assistant/chat", json=request)
    assert rejected.status_code == 200
    assert rejected.json()["available"] is False


def test_studio_assistant_recalculates_and_atomically_applies_multi_step_plan(
    client, db_session, monkeypatch
):
    owner = register_and_login(client)
    tracks = [
        _catalog_track(db_session, owner["id"], title="AI Plan One"),
        _catalog_track(db_session, owner["id"], title="AI Plan Two"),
        _catalog_track(db_session, owner["id"], title="AI Plan Three"),
    ]
    for track, bpm in zip(tracks, (120, 124, 128), strict=True):
        track.bpm = bpm
    db_session.commit()
    saved = [
        _save(client, track.id, 1000, 21_000, f"Plan {index}")
        for index, track in enumerate(tracks, start=1)
    ]
    mix = client.post("/studio/mixes", json={"title": "Assistant plan"}).json()
    for segment in saved:
        mix = client.post(
            f"/studio/mixes/{mix['id']}/items",
            json={
                "saved_segment_id": segment["id"],
                "expected_revision": mix["revision"],
            },
        ).json()
    order = [item["id"] for item in reversed(mix["segments"])]
    changes = [
        {"item_id": order[0], "transition_type": "crossfade", "duration_ms": 4000},
        {"item_id": order[1], "transition_type": "cut", "duration_ms": 0},
    ]

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "recommendation_type": "plan",
                "base_revision": 999,
                "remembered_constraints": [
                    "Keep all three tracks",
                    "Minimize BPM jumps",
                ],
                "proposed_order": order,
                "transition_changes": changes,
                "segment_bound_change": None,
                # Deliberately wrong: the authoritative backend must replace model math.
                "calculations": {
                    "current_duration_ms": 0,
                    "proposed_duration_ms": 0,
                    "transition_overlap_ms": 0,
                    "average_bpm_jump": 0,
                    "known_bpm_pairs": 0,
                },
                "warnings": [],
                "reason_tags": ["constraint-solving", "duration-math"],
                "explanation": "Reverse the arc and use one controlled overlap.",
                "confidence": 0.9,
                "requires_user_confirmation": False,
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
    chat = client.post(
        "/studio/assistant/chat",
        json={
            "mix_id": mix["id"],
            "messages": [
                {"role": "user", "content": "Keep all tracks."},
                {"role": "assistant", "content": "What should I optimize?"},
                {"role": "user", "content": "Minimize BPM jumps and use one crossfade."},
            ],
        },
    )
    assert chat.status_code == 200, chat.text
    recommendation = chat.json()["recommendation"]
    assert recommendation["base_revision"] == mix["revision"]
    assert recommendation["requires_user_confirmation"] is True
    assert recommendation["calculations"] == {
        "current_duration_ms": recommendation["calculations"]["current_duration_ms"],
        "proposed_duration_ms": 56_000,
        "transition_overlap_ms": 4_000,
        "average_bpm_jump": 4.0,
        "known_bpm_pairs": 2,
    }

    applied = client.post(
        "/studio/assistant/apply",
        json={
            "mix_id": mix["id"],
            "expected_revision": recommendation["base_revision"],
            "proposed_order": recommendation["proposed_order"],
            "transition_changes": recommendation["transition_changes"],
            "segment_bound_change": None,
        },
    )
    assert applied.status_code == 200, applied.text
    applied_mix = applied.json()["mix"]
    assert applied_mix["revision"] == mix["revision"] + 1
    assert [item["id"] for item in applied_mix["segments"]] == order
    assert applied_mix["segments"][0]["transition_type"] == "crossfade"
    assert applied_mix["segments"][0]["transition_duration_ms"] == 4000
    assert applied_mix["segments"][1]["transition_type"] == "cut"

    stale = client.post(
        "/studio/assistant/apply",
        json={
            "mix_id": mix["id"],
            "expected_revision": recommendation["base_revision"],
            "proposed_order": recommendation["proposed_order"],
            "transition_changes": recommendation["transition_changes"],
        },
    )
    assert stale.status_code == 409
