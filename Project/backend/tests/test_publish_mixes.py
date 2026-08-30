"""Unified publish policy coverage: rendered_asset vs. provider_manifest,
Discover/profile/Community visibility, playback-manifest resolution,
immutability across a draft edit, likes/saves, privacy, and the SSRF/
allowlist/bounds validation on the publish and playback paths.
"""

from pathlib import Path

from conftest import register_and_login

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.database.models.mix import Mix
from app.services import studio_service, upload_queue
from app.services.pipeline.audio_renderer import PydubAudioRenderer
from test_mixes import _patch_audius, sample_tracks
from test_studio import _catalog_track, _save

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
).read_bytes()


def _publish_provider_studio_mix(client, db_session, monkeypatch):
    """Shared setup: an owner with one published, Studio, Audius-backed mix."""

    owner = register_and_login(client)
    external = ExternalTrack(
        source="audius",
        external_id="track-9",
        title="Remote track",
        artist="Remote artist",
        duration_sec=90,
        analysis_status="completed",
        analysis_attempt_count=1,
        segment_start_second=15,
        segment_end_second=45,
        segment_method="chorus_detection",
        provider_metadata_json={"permalink": "/remoteartist/remote-track-abc"},
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
            "source_track_id": "track-9",
            "start_ms": 15_250,
            "end_ms": 45_750,
            "label": "Provider hook",
        },
    ).json()
    mix = client.post("/studio/mixes", json={"title": "Provider draft"}).json()
    mix = client.post(
        f"/studio/mixes/{mix['id']}/items",
        json={"saved_segment_id": saved["id"], "expected_revision": mix["revision"]},
    ).json()
    row = db_session.get(Mix, mix["id"])
    row.render_status = "ready"
    row.rendered_revision = row.revision
    row.rendered_audio_url = "/media/renders/temporary-composite.wav"
    db_session.commit()
    published = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert published.status_code == 200, published.text
    return owner, published.json()


def test_provider_publication_never_exposes_temporary_composite_wav(
    client, db_session, monkeypatch
):
    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    assert mix["publication_mode"] == "provider_manifest"
    assert mix["published_audio_url"] is None
    row = db_session.get(Mix, mix["id"])
    assert row.published_manifest_json is not None
    assert row.published_audio_url is None


def test_immutable_revision_survives_a_later_draft_duplicate(client, db_session, monkeypatch):
    """The published snapshot (manifest + segments) must stay exactly as
    published even though the underlying draft can keep changing through
    `duplicate_mix` -- Studio's own published-draft immutability (409 on any
    further edit to a published mix) is exercised in test_studio.py; this
    checks the *published data itself* never mutates."""

    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    first_manifest = client.get(f"/mixes/{mix['id']}/playback-manifest").json()

    duplicate = client.post(f"/studio/mixes/{mix['id']}/duplicate")
    assert duplicate.status_code == 200
    draft = duplicate.json()
    # Edit the new draft materially (retitle) -- the original published
    # mix's own manifest/segments must not move.
    client.patch(
        f"/studio/mixes/{draft['id']}",
        json={"title": "Edited copy", "expected_revision": draft["revision"]},
    )

    still_published = client.get(f"/mixes/{mix['id']}")
    assert still_published.status_code == 200
    assert still_published.json()["title"] == "Provider draft"
    second_manifest = client.get(f"/mixes/{mix['id']}/playback-manifest").json()
    assert second_manifest == first_manifest


def test_published_provider_mix_appears_in_discover_and_profile(client, db_session, monkeypatch):
    owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)

    feed = client.get("/mixes/feed").json()
    assert any(item["id"] == mix["id"] for item in feed)
    feed_item = next(item for item in feed if item["id"] == mix["id"])
    assert feed_item["publication_mode"] == "provider_manifest"

    profile = client.get(f"/users/{owner['username']}/mixes")
    assert profile.status_code == 200
    assert any(item["id"] == mix["id"] for item in profile.json())


def test_published_provider_mix_can_be_shared_as_mix_share_post(client, db_session, monkeypatch):
    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    post = client.post(
        "/posts",
        json={"kind": "mix_share", "body": "Check this out", "visibility": "public", "mix_id": mix["id"]},
    )
    assert post.status_code == 201, post.text
    body = post.json()
    assert body["mix"]["id"] == mix["id"]
    assert body["mix"]["publication_mode"] == "provider_manifest"


def test_another_permitted_user_can_fetch_the_playback_manifest_and_get_attribution(
    client, second_client, db_session, monkeypatch
):
    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    register_and_login(second_client, "bob", "bob@example.com")

    response = second_client.get(f"/mixes/{mix['id']}/playback-manifest")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "provider_manifest"
    segment = body["segments"][0]
    assert segment["availability"] == "available"
    assert segment["audio_url"].startswith("https://discoveryprovider.audius.co")
    assert segment["provider_url"] == "https://audius.co/remoteartist/remote-track-abc"
    assert "via Audius" in segment["attribution"]
    assert segment["rights_status"] == "provider_streaming"


def test_likes_and_saves_work_on_a_provider_manifest_mix(client, second_client, db_session, monkeypatch):
    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    register_and_login(second_client, "bob", "bob@example.com")

    liked = second_client.post(f"/mixes/{mix['id']}/like")
    assert liked.status_code == 200
    assert liked.json()["like_count"] == 1
    saved = second_client.post(f"/mixes/{mix['id']}/save")
    assert saved.status_code == 200
    library = second_client.get("/mixes/library").json()
    assert any(item["id"] == mix["id"] for item in library["saved"])


def test_blocked_private_and_deleted_mixes_reject_playback_manifest_access(
    client, second_client, db_session, monkeypatch
):
    owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    register_and_login(second_client, "bob", "bob@example.com")

    # Still-private (unpublished draft) mixes never resolve for anyone.
    other_draft = client.post("/studio/mixes", json={"title": "Draft only"}).json()
    assert (
        second_client.get(f"/mixes/{other_draft['id']}/playback-manifest").status_code == 404
    )

    # A block between viewer and owner hides an otherwise-published mix.
    second_client.post(f"/users/{owner['username']}/block")
    assert second_client.get(f"/mixes/{mix['id']}/playback-manifest").status_code == 404
    second_client.delete(f"/users/{owner['username']}/block")

    # A deleted mix (simulated: flip status back to draft, as a delete
    # would leave no published row queryable) is likewise unreachable.
    row = db_session.get(Mix, mix["id"])
    row.status = "draft"
    db_session.commit()
    assert client.get(f"/mixes/{mix['id']}/playback-manifest").status_code == 404


def test_publish_rejects_unallowlisted_provider_source(client, db_session, monkeypatch):
    """A segment claiming an unknown/unallowlisted source can never reach
    publication -- publish_service.ALLOWED_PROVIDERS is the only source of
    truth, never a client-controlled value."""

    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    saved = _save(client, track.id, 1000, 5000, "Solo")
    mix = client.post("/studio/mixes", json={"title": "Tamper attempt"}).json()
    mix = client.post(
        f"/studio/mixes/{mix['id']}/items",
        json={"saved_segment_id": saved["id"], "expected_revision": mix["revision"]},
    ).json()
    row = db_session.get(Mix, mix["id"])
    row.render_status = "ready"
    row.rendered_revision = row.revision
    row.rendered_audio_url = "/media/renders/fixture.wav"
    # Simulate a segment whose source was somehow set to an arbitrary,
    # unallowlisted value (never possible through the public API, which
    # only accepts 'catalog'/'audius') to prove the publish-time allowlist
    # check is real, not just a client-side assumption.
    row.segments[0].source = "https://evil.example/track.mp3"
    db_session.commit()

    blocked = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert blocked.status_code == 422
    assert "allowlisted" in blocked.json()["detail"]


def test_playback_manifest_never_trusts_a_stored_url_for_provider_audio(
    client, db_session, monkeypatch
):
    """Even if a stored manifest segment somehow carried an attacker-chosen
    URL, the playback-manifest endpoint must still rebuild the audio_url
    itself from (source, source_track_id) -- never read a URL field back
    out of the manifest. This is what prevents SSRF via a tampered
    manifest."""

    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    row = db_session.get(Mix, mix["id"])
    tampered = dict(row.published_manifest_json)
    tampered["segments"] = [dict(tampered["segments"][0])]
    tampered["segments"][0]["audio_url"] = "http://169.254.169.254/latest/meta-data/"
    row.published_manifest_json = tampered
    db_session.commit()

    resolved = client.get(f"/mixes/{mix['id']}/playback-manifest").json()
    segment = resolved["segments"][0]
    assert segment["audio_url"] != "http://169.254.169.254/latest/meta-data/"
    assert segment["audio_url"].startswith("https://discoveryprovider.audius.co")


def test_unknown_provider_track_reports_unavailable_without_crashing(client, db_session, monkeypatch):
    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    row = db_session.get(Mix, mix["id"])
    manifest = dict(row.published_manifest_json)
    manifest["segments"] = [dict(manifest["segments"][0])]
    manifest["segments"][0]["source"] = "spotify"
    row.published_manifest_json = manifest
    db_session.commit()

    resolved = client.get(f"/mixes/{mix['id']}/playback-manifest")
    assert resolved.status_code == 200
    segment = resolved.json()["segments"][0]
    assert segment["availability"] == "unavailable"
    assert segment["audio_url"] is None
    assert segment["unavailable_reason"] == "unknown_provider"


def test_known_broken_provider_track_reported_unavailable(client, db_session, monkeypatch):
    from app.services import known_broken_tracks
    from app.schemas import Track

    _owner, mix = _publish_provider_studio_mix(client, db_session, monkeypatch)
    known_broken_tracks.mark_broken(
        db_session,
        Track(
            source="audius",
            source_track_id="track-9",
            title="x",
            artist="x",
            audio_url="https://discoveryprovider.audius.co/v1/tracks/track-9/stream",
            duration_seconds=90,
        ),
        "download_failed_http_404",
    )

    resolved = client.get(f"/mixes/{mix['id']}/playback-manifest")
    assert resolved.status_code == 200
    segment = resolved.json()["segments"][0]
    assert segment["availability"] == "unavailable"
    assert segment["audio_url"] is None


def test_invalid_bounds_and_transitions_are_rejected_at_publish(client, db_session):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    saved = _save(client, track.id, 1000, 5000, "Solo")
    mix = client.post("/studio/mixes", json={"title": "Bad bounds"}).json()
    mix = client.post(
        f"/studio/mixes/{mix['id']}/items",
        json={"saved_segment_id": saved["id"], "expected_revision": mix["revision"]},
    ).json()
    row = db_session.get(Mix, mix["id"])
    row.render_status = "ready"
    row.rendered_revision = row.revision
    row.rendered_audio_url = "/media/renders/fixture.wav"
    row.segments[0].source_start_ms = 5000
    row.segments[0].source_end_ms = 1000  # end before start
    db_session.commit()

    blocked = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert blocked.status_code == 422
    assert "bounds" in blocked.json()["detail"]


def test_transition_duration_ceiling_is_enforced_at_publish(client, db_session):
    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    first = _save(client, track.id, 1000, 5000, "First")
    second = _save(client, track.id, 6000, 10_000, "Second")
    mix = client.post("/studio/mixes", json={"title": "Too long transition"}).json()
    for item in (first, second):
        mix = client.post(
            f"/studio/mixes/{mix['id']}/items",
            json={"saved_segment_id": item["id"], "expected_revision": mix["revision"]},
        ).json()
    row = db_session.get(Mix, mix["id"])
    row.render_status = "ready"
    row.rendered_revision = row.revision
    row.rendered_audio_url = "/media/renders/fixture.wav"
    row.segments[0].transition_duration_ms = 999_999
    db_session.commit()

    blocked = client.post(f"/studio/mixes/{mix['id']}/publish")
    assert blocked.status_code == 422
    assert "transition" in blocked.json()["detail"].lower()


def test_regular_provider_backed_mix_uses_the_same_centralized_policy(client, monkeypatch):
    """A plain generated mix (routers/mixes.py) and a Studio mix both defer
    to publish_service.publish_mix -- this asserts the regular-mix path
    picks provider_manifest exactly like the Studio one does, i.e. there is
    one shared decision, not two independently-coded rules."""

    _patch_audius(monkeypatch, sample_tracks())
    register_and_login(client)
    mix = client.post("/mixes/start", json={"prompt": "energetic electronic"}).json()
    assert len(mix["segments"]) == 2
    assert mix["segments"][0]["source"] == "audius"

    published = client.post(f"/mixes/{mix['id']}/publish")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["publication_mode"] == "provider_manifest"
    assert body["published_audio_url"] is None

    manifest = client.get(f"/mixes/{mix['id']}/playback-manifest")
    assert manifest.status_code == 200, manifest.text
    manifest_body = manifest.json()
    assert manifest_body["mode"] == "provider_manifest"
    assert len(manifest_body["segments"]) == 2
    assert all(item["source"] == "audius" for item in manifest_body["segments"])


def test_published_rendered_asset_is_excluded_from_temporary_render_cleanup(
    client, db_session, monkeypatch
):
    from app.services.pipeline import audio_renderer

    owner = register_and_login(client)
    track = _catalog_track(db_session, owner["id"])
    first = _save(client, track.id, 1000, 5000, "First")
    second = _save(client, track.id, 6000, 10_000, "Second")
    mix = client.post("/studio/mixes", json={"title": "Cleanup-safe"}).json()
    for item in (first, second):
        mix = client.post(
            f"/studio/mixes/{mix['id']}/items",
            json={"saved_segment_id": item["id"], "expected_revision": mix["revision"]},
        ).json()

    def render_inline(mix_id, owner_id, revision, priority=4):
        del priority
        row = studio_service.owned_studio_mix(db_session, owner_id, mix_id)
        studio_service.render_mix(db_session, row, PydubAudioRenderer(), expected_revision=revision)

    monkeypatch.setattr(upload_queue.upload_queue, "submit_studio_render", render_inline)
    rendered = client.post(f"/studio/mixes/{mix['id']}/render").json()
    from time import monotonic, sleep

    deadline = monotonic() + 5
    while rendered["render_status"] == "rendering" and monotonic() < deadline:
        sleep(0.05)
        rendered = client.get(f"/studio/mixes/{mix['id']}").json()
    assert rendered["render_status"] == "ready"

    published = client.post(f"/studio/mixes/{mix['id']}/publish").json()
    published_url = published["published_audio_url"]
    assert published_url and "/renders/published/" in published_url
    filename = published_url.rsplit("/", 1)[-1]
    published_path = upload_queue.UPLOAD_DIR / "renders" / "published" / filename
    assert published_path.is_file()

    # Simulate the TTL sweep running long after publish -- it must never
    # touch the published subdirectory (see audio_renderer._sweep_stale_renders,
    # which only iterates the top-level renders/ directory).
    monkeypatch.setattr(audio_renderer, "RENDERED_AUDIO_TTL_SECONDS", 0.0)
    audio_renderer._sweep_stale_renders(audio_renderer._render_dir())
    assert published_path.is_file()

    # The test client talks to the app directly, without the /api prefix
    # public_api_url() adds for real deployments.
    served = client.get("/media/renders/published/" + filename)
    assert served.status_code == 200
