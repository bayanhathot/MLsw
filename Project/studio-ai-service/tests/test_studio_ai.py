import json

import httpx
from fastapi.testclient import TestClient
from studio_ai.main import app


def _request():
    return {
        "messages": [{"role": "user", "content": "Keep the vocal phrase"}],
        "context": {"active_segment": {"id": 7, "duration_ms": 60000}},
    }


def test_manual_health_does_not_require_ollama(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert TestClient(app).get("/health").status_code == 200
    assert TestClient(app).get("/ready").status_code == 503


def test_chat_reuses_capacity_guard_and_returns_structured_result(monkeypatch):
    released = []
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(
        "studio_ai.main.prompt_parser._acquire_ollama_slot", lambda _timeout: lambda: released.append(True)
    )
    monkeypatch.setattr("studio_ai.main.prompt_parser._record_ollama_call", lambda *_: None)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": json.dumps(
                    {
                        "recommendation_type": "segment_bounds",
                        "candidate_id": 7,
                        "proposed_start_ms": 1000,
                        "proposed_end_ms": 5000,
                        "proposed_order": None,
                        "transition_change": None,
                        "reason_tags": ["phrase"],
                        "explanation": "A phrase-aligned alternative.",
                        "confidence": 0.8,
                        "requires_user_confirmation": False,
                    }
                )
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

    monkeypatch.setattr("studio_ai.main.httpx.Client", Client)
    response = TestClient(app).post(
        "/internal/studio-ai/chat",
        json={
            "messages": [
                {"role": "user", "content": "Keep this but make it stronger"},
                {"role": "assistant", "content": "Which constraint matters most?"},
                {"role": "user", "content": "Keep the vocal phrase"},
            ],
            "context": {"active_segment": {"id": 7, "duration_ms": 60000}},
        },
    )
    assert response.status_code == 200
    assert response.json()["requires_user_confirmation"] is True
    assert released == [True]


def test_internal_route_hides_behind_shared_token(monkeypatch):
    monkeypatch.setenv("STUDIO_AI_INTERNAL_TOKEN", "expected-token")
    response = TestClient(app).post("/internal/studio-ai/chat", json=_request())
    assert response.status_code == 404


def test_timeout_releases_capacity_and_reports_gateway_timeout(monkeypatch):
    released = []
    outcomes = []
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(
        "studio_ai.main.prompt_parser._acquire_ollama_slot",
        lambda _timeout: lambda: released.append(True),
    )
    monkeypatch.setattr(
        "studio_ai.main.prompt_parser._record_ollama_call",
        lambda _latency, outcome: outcomes.append(outcome),
    )

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("model timed out")

    monkeypatch.setattr("studio_ai.main.httpx.Client", Client)
    response = TestClient(app).post("/internal/studio-ai/chat", json=_request())
    assert response.status_code == 504
    assert released == [True]
    assert outcomes == ["timeout"]


def test_invalid_model_structure_fails_closed(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(
        "studio_ai.main.prompt_parser._acquire_ollama_slot", lambda _timeout: lambda: None
    )
    monkeypatch.setattr("studio_ai.main.prompt_parser._record_ollama_call", lambda *_: None)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "not-json"}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr("studio_ai.main.httpx.Client", Client)
    response = TestClient(app).post("/internal/studio-ai/chat", json=_request())
    assert response.status_code == 502
