"""Coverage for the internal pipeline/Ollama debug panel: the flag gate,
the Ollama health probe, last-call tracking, and the per-session trace the
debug endpoint reads back."""

import os

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import register_and_login

from app.core.config import pipeline_debug_enabled
from app.database.models.catalog import CatalogTrack
from app.services import pipeline_debug_service, prompt_parser
from app.services.pipeline.ollama_health import check_ollama_health


def test_pipeline_debug_enabled_parses_common_truthy_values(monkeypatch):
    monkeypatch.delenv("ENABLE_PIPELINE_DEBUG", raising=False)
    assert pipeline_debug_enabled() is False

    for value in ("1", "true", "True", "yes"):
        monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", value)
        assert pipeline_debug_enabled() is True

    for value in ("0", "false", "", "nah"):
        monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", value)
        assert pipeline_debug_enabled() is False


def test_ollama_health_reports_unconfigured_without_a_network_call(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    def unexpected_call(*args, **kwargs):
        raise AssertionError("check_ollama_health must not call out with no base URL configured")

    monkeypatch.setattr(httpx.Client, "get", unexpected_call)
    health = check_ollama_health()
    assert health == {
        "configured": False,
        "reachable": False,
        "error": "OLLAMA_BASE_URL is not set.",
        "configured_model": None,
        "loaded_models": [],
    }


def test_ollama_health_reports_loaded_models_when_reachable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")

    def fake_get(self, url, *args, **kwargs):
        assert url == "http://ollama.invalid/api/ps"
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen3:8b"}, {"not_a_name": "x"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    health = check_ollama_health()
    assert health["configured"] is True
    assert health["reachable"] is True
    assert health["error"] is None
    assert health["configured_model"] == "qwen3:8b"
    assert health["loaded_models"] == ["qwen3:8b"]


def test_ollama_health_degrades_to_unreachable_on_error(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")

    def timeout(self, url, *args, **kwargs):
        raise httpx.ConnectTimeout("slow", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", timeout)
    health = check_ollama_health()
    assert health["configured"] is True
    assert health["reachable"] is False
    assert health["loaded_models"] == []
    assert health["error"]


def test_last_ollama_call_is_tracked_on_success_and_failure(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")

    def failing(*args, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.Client, "post", failing)
    prompt_parser.parse_prompt("calm lofi")
    failed_call = prompt_parser.get_last_ollama_call()
    assert failed_call["ok"] is False
    assert failed_call["at"] is not None
    assert failed_call["latency_ms"] >= 0

    def succeeding(*args, **kwargs):
        return httpx.Response(
            200,
            json={"response": '{"mood":"calm","energy":"low","vocals":"less","genres":[],"search_query":"x"}'},
            request=httpx.Request("POST", "http://x"),
        )

    monkeypatch.setattr(httpx.Client, "post", succeeding)
    prompt_parser.parse_prompt("calm lofi")
    ok_call = prompt_parser.get_last_ollama_call()
    assert ok_call["ok"] is True
    assert ok_call["at"] >= failed_call["at"]


def test_pipeline_debug_endpoint_is_404_when_disabled(client, monkeypatch):
    monkeypatch.delenv("ENABLE_PIPELINE_DEBUG", raising=False)
    register_and_login(client)
    assert client.get("/debug/pipeline").status_code == 404


def test_pipeline_debug_endpoint_works_without_login_when_enabled(client, monkeypatch):
    # Deliberately no login here: this endpoint exists to diagnose a live
    # deployment before anyone necessarily has an account on it, gated by
    # ENABLE_PIPELINE_DEBUG alone (see routers/debug.py's module docstring).
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    assert client.get("/debug/pipeline").status_code == 200


def test_pipeline_debug_endpoint_reports_stage_traces_for_recent_sessions(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    # No login: anonymous sessions are already supported end to end
    # (get_optional_current_user), and so is reading this panel now.

    started = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    assert started.status_code == 200
    session_id = started.json()["id"]

    payload = client.get("/debug/pipeline").json()
    assert payload["ollama"]["configured"] in (True, False)
    assert "last_call" in payload["ollama"]

    entry = next(item for item in payload["sessions"] if item["session_id"] == session_id)
    trace = entry["trace"]
    assert entry["has_prepared_next"] is False
    assert trace["vibe_understander"]["invoked"] is True
    assert trace["candidate_retriever"]["implementation"] == "CatalogTrackRetriever"
    assert trace["candidate_retriever"]["candidate_count"] >= 1
    assert trace["segment_selector"]["implementation"]
    assert trace["transition_planner"]["style"] in ("crossfade", "cut")
    assert trace["audio_renderer"]["implementation"]
    assert isinstance(trace["audio_renderer"]["is_pass_through"], bool)
    # The URL actually handed to the player, and (only set on a
    # pass-through) why -- see audio_renderer.RenderedAudio.fallback_reason.
    assert trace["audio_renderer"]["resolved_audio_url"]
    assert trace["audio_renderer"]["fallback_reason"] is None

    prepared = client.post(f"/sessions/{session_id}/prepare-next")
    assert prepared.status_code == 200
    payload_prepared = client.get("/debug/pipeline").json()
    entry_prepared = next(
        item for item in payload_prepared["sessions"] if item["session_id"] == session_id
    )
    assert entry_prepared["has_prepared_next"] is True

    feedback = client.post(f"/sessions/{session_id}/feedback", json={"feedback": "More energy"})
    assert feedback.status_code == 200

    payload_after = client.get("/debug/pipeline").json()
    entry_after = next(item for item in payload_after["sessions"] if item["session_id"] == session_id)
    # Feedback mutates the stored intent deterministically; it never calls
    # the LLM again, so the trace must say so rather than implying it did.
    assert entry_after["trace"]["vibe_understander"]["invoked"] is False
    # apply_feedback's intent mutation explicitly invalidates a prepared item.
    assert entry_after["has_prepared_next"] is False


def test_pipeline_debug_score_breakdown_reflects_a_strong_catalog_match(
    client, monkeypatch, db_session
):
    """orchestrator.retrieve_candidates_with_fallback's tier-1 (strong
    catalog match) path calls CatalogTrackRetriever.retrieve_with_scores
    directly rather than retrieve() -- deliberately, so the strong/weak
    decision itself never reads back the shared last_candidate_scores
    instance attribute (see catalog_retriever.CatalogTrackRetriever's
    docstring for the concurrency reason). But the debug trace still reads
    that same attribute after the fact, so retrieve_candidates_with_fallback
    must still write this call's own breakdown onto it when a strong match
    serves directly -- otherwise the debug trace would show stale or empty
    data for exactly the case this test exercises."""

    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    db_session.add(CatalogTrack(
        title="Debug Trace Match", artist="Zzq Debug Artist", genre="house",
        visibility="public", storage_name="x.wav", content_type="audio/wav",
    ))
    db_session.commit()

    started = client.post(
        "/sessions/start",
        json={"prompt": "play something by Zzq Debug Artist, house music"},
    )
    assert started.status_code == 200
    session_id = started.json()["id"]
    assert started.json()["nowPlaying"]["title"] == "Debug Trace Match"

    payload = client.get("/debug/pipeline").json()
    entry = next(item for item in payload["sessions"] if item["session_id"] == session_id)
    trace = entry["trace"]
    assert trace["candidate_retriever"]["name"] == "catalog"
    assert trace["candidate_retriever"]["fell_back"] is False
    breakdown = trace["candidate_retriever"]["score_breakdown"]
    assert breakdown is not None
    assert breakdown["genre"] == 1.0
    assert breakdown["total"] == 1.0


def test_pipeline_debug_tier_distinguishes_last_resort_from_a_weak_primary_match(
    client, monkeypatch, db_session
):
    """fell_back alone can't tell orchestrator.retrieve_candidates_with_fallback's
    tier 3 (a weak-but-real primary match) apart from tier 4 (the
    intent-blind last-resort tier) -- both are catalog-sourced and both can
    read fell_back either way depending on which object actually served.
    The new "tier" field (session_manager.py) is the one thing this test
    suite didn't already have a way to check end-to-end.

    Reaching tier 4 for a no-artist request needs an explicit assist since
    the issue-1 fix (catalog_retriever.py's no-artist branch no longer
    hard-filters to one mood_bucket): tier 1's own query is now a superset
    of whatever tier 4's last_resort_tracks() would find (same visibility
    filter, a much larger cap -- NO_ARTIST_CANDIDATE_POOL_CAP vs. the
    caller's own `limit`), so tier 1 coming back empty now implies tier 4
    would too, in real usage. Shrinking that cap to 0 here is purely to
    keep exercising tier 4's code path in a test, not a realistic
    production scenario -- tier 1 and tier 4 use the same visibility
    filter, just different limits."""

    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks", lambda prompt, limit=5: []
    )
    db_session.add(CatalogTrack(
        title="Unrelated Smooth Row", artist="Cuemix AI DJ", mood_bucket="smooth",
        visibility="public", storage_name="x.wav", content_type="audio/wav",
    ))
    db_session.commit()
    monkeypatch.setattr("app.services.pipeline.catalog_retriever.NO_ARTIST_CANDIDATE_POOL_CAP", 0)

    started = client.post("/sessions/start", json={"prompt": "smooth focus music work"})
    assert started.status_code == 200
    session_id = started.json()["id"]

    payload = client.get("/debug/pipeline").json()
    entry = next(item for item in payload["sessions"] if item["session_id"] == session_id)
    trace = entry["trace"]["candidate_retriever"]
    assert trace["tier"] == "last_resort"
    assert trace["name"] == "catalog"
    assert trace["fell_back"] is True


def test_pipeline_debug_websocket_rejects_untrusted_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/debug/ws", headers={"Origin": "https://evil.example"}):
            pass
    assert exc_info.value.code == 4403


def test_pipeline_debug_websocket_closes_when_disabled(client, monkeypatch):
    monkeypatch.delenv("ENABLE_PIPELINE_DEBUG", raising=False)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/debug/ws"):
            pass
    assert exc_info.value.code == 4404


def test_pipeline_debug_websocket_connects_when_enabled_without_login(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    with client.websocket_connect("/debug/ws") as socket:
        socket.send_text("ready")


def test_pipeline_debug_websocket_connects_when_enabled_and_authenticated(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    register_and_login(client)
    with client.websocket_connect("/debug/ws") as socket:
        socket.send_text("ready")


# --- D6b: pipeline_debug_hub ported to Redis pub/sub -----------------------


def test_session_creation_survives_a_broken_pipeline_debug_publish(client, monkeypatch):
    """The debug panel's own plumbing must never be able to break or block
    the real session-loop request path -- same standard as
    test_admin_debug.py's identical test for admin_debug_events.sync_publish.
    Patches the actual point of failure a real deployment could hit (the
    Redis client notify_pipeline_debug_change() gets), not the wrapper
    function itself, so this exercises its real internal try/except."""

    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")

    class _BoomClient:
        def publish(self, *args, **kwargs):
            raise RuntimeError("redis publish is broken")

    monkeypatch.setattr(pipeline_debug_service, "get_sync_redis_client", lambda: _BoomClient())

    response = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    assert response.status_code == 200


@pytest.mark.skipif(
    not os.getenv("REDIS_URL", "").strip(),
    reason="a real live-push proof requires a real REDIS_URL",
)
def test_pipeline_debug_websocket_receives_a_live_push_from_a_different_replica(
    client, second_client, monkeypatch
):
    """Two-client-style live proof, same standard as
    test_admin_debug.py::test_admin_debug_channel_pushes_a_live_session_update
    -- client and second_client are two independent TestClient(app) instances,
    each with its own ASGI lifespan/event loop (see conftest.py's own
    fixtures), the closest this test suite gets to two real BACKEND_WORKERS
    replicas. second_client holds the debug websocket open; a real
    session-creating request from `client` (a different process's own
    session_manager.create_session -> notify_pipeline_debug_change() call)
    must arrive on second_client's open socket without any manual refetch,
    proving this reuses the real Redis-backed fanout (D6b) rather than the
    old in-process-only anyio bridge, which could never have delivered this
    across two separate TestClient instances at all."""

    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")

    with second_client.websocket_connect("/debug/ws") as socket:
        started = client.post("/sessions/start", json={"prompt": "smooth focus music"})
        assert started.status_code == 200

        envelope = socket.receive_json()
        assert envelope["type"] == "pipeline_trace_updated"
