"""Coverage for the internal pipeline/Ollama debug panel: the flag gate,
the Ollama health probe, last-call tracking, and the per-session trace the
debug endpoint reads back."""

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import register_and_login

from app.core.config import pipeline_debug_enabled
from app.services import prompt_parser
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


def test_pipeline_debug_endpoint_requires_login_even_when_enabled(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    assert client.get("/debug/pipeline").status_code == 401


def test_pipeline_debug_endpoint_reports_stage_traces_for_recent_sessions(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    register_and_login(client)

    started = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    assert started.status_code == 200
    session_id = started.json()["id"]

    payload = client.get("/debug/pipeline").json()
    assert payload["ollama"]["configured"] in (True, False)
    assert "last_call" in payload["ollama"]

    entry = next(item for item in payload["sessions"] if item["session_id"] == session_id)
    trace = entry["trace"]
    assert trace["vibe_understander"]["invoked"] is True
    assert trace["candidate_retriever"]["implementation"] == "CatalogTrackRetriever"
    assert trace["candidate_retriever"]["candidate_count"] >= 1
    assert trace["segment_selector"]["implementation"]
    assert trace["transition_planner"]["style"] in ("crossfade", "cut")
    assert trace["audio_renderer"]["implementation"]
    assert isinstance(trace["audio_renderer"]["is_pass_through"], bool)

    feedback = client.post(f"/sessions/{session_id}/feedback", json={"feedback": "More energy"})
    assert feedback.status_code == 200

    payload_after = client.get("/debug/pipeline").json()
    entry_after = next(item for item in payload_after["sessions"] if item["session_id"] == session_id)
    # Feedback mutates the stored intent deterministically; it never calls
    # the LLM again, so the trace must say so rather than implying it did.
    assert entry_after["trace"]["vibe_understander"]["invoked"] is False


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


def test_pipeline_debug_websocket_requires_auth_when_enabled(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/debug/ws"):
            pass
    assert exc_info.value.code == 4401


def test_pipeline_debug_websocket_connects_when_enabled_and_authenticated(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PIPELINE_DEBUG", "true")
    register_and_login(client)
    with client.websocket_connect("/debug/ws") as socket:
        socket.send_text("ready")
