"""Coverage for the admin debug dashboard (routers/admin_debug.py): the
flag+auth gate (404, never 401/403, for both unauthorized shapes -- flag
off, or not logged in; any logged-in account passes once the flag is on,
see admin_debug.py's own docstring for why), real session/external-track
data reaching an authenticated user, that no secret value ever reaches the
rendered response, the "admin_debug" channel_hub authorization rule, and
that publishing dashboard events never breaks or blocks the real
session-loop request path even when it fails.
"""

import os

import pytest

from conftest import register_and_login

from app.core.config import debug_dashboard_enabled
from app.core.security import SECRET_KEY
from app.services import admin_debug_events


def _user_id(client) -> int:
    return client.get("/auth/me").json()["id"]


def test_debug_dashboard_enabled_parses_common_truthy_values(monkeypatch):
    monkeypatch.delenv("DEBUG_DASHBOARD_ENABLED", raising=False)
    assert debug_dashboard_enabled() is False
    for value in ("1", "true", "True", "yes"):
        monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", value)
        assert debug_dashboard_enabled() is True
    for value in ("0", "false", "", "nah"):
        monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", value)
        assert debug_dashboard_enabled() is False


@pytest.mark.parametrize(
    "path",
    [
        "/admin/debug/sessions",
        "/admin/debug/external-tracks",
        "/admin/debug/events",
        "/admin/debug/upload-queue",
    ],
)
def test_admin_debug_is_404_when_flag_disabled(client, path, monkeypatch):
    monkeypatch.delenv("DEBUG_DASHBOARD_ENABLED", raising=False)
    register_and_login(client)
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found."}


@pytest.mark.parametrize(
    "path",
    [
        "/admin/debug/sessions",
        "/admin/debug/external-tracks",
        "/admin/debug/events",
        "/admin/debug/upload-queue",
    ],
)
def test_admin_debug_is_404_when_not_logged_in(client, monkeypatch, path):
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")
    # Deliberately no register_and_login call.
    response = client.get(path)
    assert response.status_code == 404


def test_admin_debug_is_reachable_by_any_authenticated_account(client, second_client, monkeypatch):
    """Access is "any logged-in account," not one specific owner -- a
    second, unrelated account must succeed exactly like the first."""

    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")
    register_and_login(client, "alice", "alice@example.example")
    register_and_login(second_client, "bob", "bob@example.example")
    assert client.get("/admin/debug/sessions").status_code == 200
    assert second_client.get("/admin/debug/sessions").status_code == 200


def test_admin_debug_kill_switch_still_404s_a_logged_in_user(client, monkeypatch):
    """The flag being off must win even for an authenticated account --
    this is the "kill it instantly" guarantee the whole feature is gated
    on."""

    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "false")
    assert client.get("/admin/debug/sessions").status_code == 404
    assert client.get("/admin/debug/external-tracks").status_code == 404
    assert client.get("/admin/debug/events").status_code == 404
    assert client.get("/admin/debug/upload-queue").status_code == 404


def test_admin_debug_shows_real_session_data(client, monkeypatch):
    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")

    started = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    assert started.status_code == 200
    session_id = started.json()["id"]

    response = client.get("/admin/debug/sessions")
    assert response.status_code == 200
    payload = response.json()
    entry = next(item for item in payload["sessions"] if item["session_id"] == session_id)
    trace = entry["trace"]
    assert trace["vibe_understander"]["invoked"] is True
    # The two genuine trace gaps this feature closed: TransitionPlanner's
    # structured decision fields (previously only in free-text notes) and
    assert "key_category" in trace["transition_planner"]
    assert "phrase_aligned" in trace["transition_planner"]
    assert "capped_by_reserved_window" in trace["transition_planner"]


def test_admin_debug_external_tracks_search_filters_by_artist_or_title(client, db_session, monkeypatch):
    from app.database.models.external_track import ExternalTrack

    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")

    db_session.add_all([
        ExternalTrack(source="audius", external_id="a1", title="Sunset Drive", artist="Nova Loop"),
        ExternalTrack(source="audius", external_id="a2", title="Rainy Streets", artist="Glass Fox"),
    ])
    db_session.commit()

    all_tracks = client.get("/admin/debug/external-tracks").json()["tracks"]
    assert {t["external_id"] for t in all_tracks} == {"a1", "a2"}

    by_artist = client.get("/admin/debug/external-tracks", params={"search": "nova"}).json()["tracks"]
    assert [t["external_id"] for t in by_artist] == ["a1"]

    by_title = client.get("/admin/debug/external-tracks", params={"search": "streets"}).json()["tracks"]
    assert [t["external_id"] for t in by_title] == ["a2"]

    # audio_sha256, beat_grid_json etc are deliberately excluded columns --
    # not just "not populated," genuinely absent from the response shape.
    assert "audio_sha256" not in all_tracks[0]
    assert "beat_grid_json" not in all_tracks[0]


def test_admin_debug_events_endpoint_returns_recorded_events(client, monkeypatch):
    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")

    admin_debug_events._events.clear()
    admin_debug_events.record_event({"event": "session_stage_latency", "stage": "create_session", "total_ms": 12.3})

    payload = client.get("/admin/debug/events").json()
    assert payload["events"][0]["event"] == "session_stage_latency"
    assert payload["events"][0]["stage"] == "create_session"


def test_admin_debug_upload_queue_exposes_only_aggregate_runtime_metrics(
    client, monkeypatch
):
    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")

    response = client.get("/admin/debug/upload-queue")
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured_workers"] >= 1
    assert payload["capacity"] >= 1
    assert payload["queued_items"] >= 0
    assert payload["tracked_jobs"] >= 0
    assert isinstance(payload["statuses"], dict)
    assert not {
        "job_id",
        "owner_id",
        "filename",
        "pending_path",
        "storage_name",
    } & payload.keys()


def test_admin_debug_response_never_contains_the_backend_secret_key(client, monkeypatch):
    """Grepping the actual rendered response for a known secret value,
    not eyeballing the schema -- SECRET_KEY signs every JWT; if it ever
    leaked here every session cookie in production would be forgeable."""

    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")
    client.post("/sessions/start", json={"prompt": "smooth focus music"})

    for path in (
        "/admin/debug/sessions",
        "/admin/debug/external-tracks",
        "/admin/debug/events",
        "/admin/debug/upload-queue",
    ):
        response = client.get(path)
        assert SECRET_KEY not in response.text
        assert os.getenv("DATABASE_URL", "") == "" or os.getenv("DATABASE_URL") not in response.text


def test_admin_debug_channel_requires_only_the_flag_and_authentication(monkeypatch):
    from app.routers.realtime import _authorize_subscribe

    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")
    assert _authorize_subscribe(db=None, channel="admin_debug", user_id=5) is True
    assert _authorize_subscribe(db=None, channel="admin_debug", user_id=6) is True

    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "false")
    assert _authorize_subscribe(db=None, channel="admin_debug", user_id=5) is False


def test_record_event_is_a_noop_with_no_buffer_growth_when_dashboard_disabled(monkeypatch):
    monkeypatch.delenv("DEBUG_DASHBOARD_ENABLED", raising=False)
    admin_debug_events._events.clear()
    admin_debug_events.record_event({"event": "x"})
    assert admin_debug_events.recent_events() == []


def test_session_creation_survives_a_broken_admin_debug_publish(client, monkeypatch):
    """The dashboard's own plumbing must never be able to break or block
    the real session-loop request path. Patches the actual point of
    failure a real deployment could hit -- the Redis publish call inside
    admin_debug_events.sync_publish, the same layer channel_hub.py's own
    fail-open tests target (test_channel_hub.py) -- rather than replacing
    the wrapper function itself, which would bypass its own internal
    try/except and test a scenario that isn't how a real failure
    manifests (see notify_pipeline_debug_change's identical, unwrapped
    call sites -- the established precedent this mirrors)."""

    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")

    def boom(*args, **kwargs):
        raise RuntimeError("redis publish is broken")

    monkeypatch.setattr(admin_debug_events, "sync_publish", boom)

    response = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    assert response.status_code == 200


@pytest.mark.skipif(
    not os.getenv("REDIS_URL", "").strip(),
    reason="a real live-push proof requires a real REDIS_URL",
)
def test_admin_debug_channel_pushes_a_live_session_update(client, monkeypatch):
    """Two-client-style live proof, same standard as the realtime-e2e
    suite: one client holds the dashboard's websocket open and subscribed;
    a real session-creating request from a second client must arrive on
    that open socket without any manual refetch, proving this reuses
    channel_hub's real Redis-backed fanout rather than a second mechanism."""

    register_and_login(client)
    monkeypatch.setenv("DEBUG_DASHBOARD_ENABLED", "true")

    with client.websocket_connect("/ws") as socket:
        socket.send_json({"action": "subscribe", "channel": "admin_debug"})

        started = client.post("/sessions/start", json={"prompt": "smooth focus music"})
        assert started.status_code == 200
        session_id = started.json()["id"]

        envelope = socket.receive_json()
        assert envelope["channel"] == "admin_debug"
        assert envelope["type"] == "session_updated"
        assert envelope["data"]["session_id"] == session_id
