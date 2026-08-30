import json
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from time import sleep

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from studio_ai.main import app
from studio_ai.schemas import AddItem, Recommendation


def _request():
    return {
        "messages": [{"role": "user", "content": "Keep the vocal phrase"}],
        "context": {"active_segment": {"id": 7, "duration_ms": 60000}},
    }


def _plan():
    return {
        "recommendation_type": "plan",
        "base_revision": 4,
        "remembered_constraints": ["Keep the first track", "Stay under 2:30"],
        "proposed_order": [11, 12, 13],
        "transition_changes": [
            {"item_id": 11, "transition_type": "crossfade", "duration_ms": 4000}
        ],
        "segment_bound_change": None,
        "calculations": {
            "current_duration_ms": 160000,
            "proposed_duration_ms": 146000,
            "transition_overlap_ms": 8000,
            "average_bpm_jump": 4.5,
            "known_bpm_pairs": 2,
        },
        "warnings": ["One track has no key analysis"],
        "reason_tags": ["duration", "tempo-arc"],
        "explanation": "The order preserves the opener and reduces tempo jumps.",
        "confidence": 0.84,
        "requires_user_confirmation": False,
    }


def test_manual_health_does_not_require_ollama(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    health = TestClient(app).get("/health")
    assert health.status_code == 200
    assert health.json()["thinking_enabled"] is True
    assert health.json()["keep_alive"] == "-1"
    assert TestClient(app).get("/ready").status_code == 503


def test_chat_reuses_capacity_guard_and_returns_structured_result(monkeypatch):
    released = []
    posted = {}
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
            return {"message": {"role": "assistant", "content": json.dumps(_plan())}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            posted["url"] = url
            posted["json"] = kwargs["json"]
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
            "context": {
                "mix": {
                    "revision": 4,
                    "items": [{"item_id": 11}, {"item_id": 12}, {"item_id": 13}],
                }
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["requires_user_confirmation"] is True
    assert posted["url"] == "http://ollama/api/chat"
    assert posted["json"]["think"] is True
    assert posted["json"]["keep_alive"] == -1
    assert [message["role"] for message in posted["json"]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "AUTHORITATIVE_CONTEXT=" in posted["json"]["messages"][0]["content"]
    assert released == [True]


def test_known_qwen_thinking_prefix_is_repaired_narrowly(monkeypatch):
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
            return {"message": {"content": '{"' + json.dumps(_plan())}}

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
    assert response.status_code == 200
    assert response.json()["recommendation_type"] == "plan"


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
            return {"message": {"role": "assistant", "content": "not-json"}}

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


def test_twenty_call_stress_is_bounded_and_fails_fast_when_busy(monkeypatch):
    slots = BoundedSemaphore(2)
    state_lock = Lock()
    state = {"active": 0, "high_water": 0}
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_QUEUE_WAIT_SECONDS", "0.05")
    monkeypatch.setattr("studio_ai.main.prompt_parser._record_ollama_call", lambda *_: None)
    monkeypatch.setattr("studio_ai.main.prompt_parser._record_ollama_shed", lambda: None)

    def acquire(timeout):
        return slots.release if slots.acquire(timeout=timeout) else None

    monkeypatch.setattr("studio_ai.main.prompt_parser._acquire_ollama_slot", acquire)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            clarification = _plan()
            clarification.update(
                {
                    "recommendation_type": "clarification",
                    "base_revision": None,
                    "proposed_order": None,
                    "transition_changes": [],
                    "calculations": None,
                    "warnings": [],
                    "explanation": "Which constraint has priority?",
                }
            )
            return {"message": {"content": json.dumps(clarification)}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            with state_lock:
                state["active"] += 1
                state["high_water"] = max(state["high_water"], state["active"])
            sleep(0.1)
            with state_lock:
                state["active"] -= 1
            return Response()

    monkeypatch.setattr("studio_ai.main.httpx.Client", Client)

    def invoke(_index):
        return TestClient(app).post("/internal/studio-ai/chat", json=_request()).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(invoke, range(20)))

    assert state["high_water"] <= 2
    assert set(statuses) <= {200, 503}
    assert statuses.count(200) >= 2
    assert len(statuses) == 20


def _minimal_recommendation(**overrides):
    payload = {
        "recommendation_type": "explanation",
        "explanation": "Here is what I found.",
        "confidence": 0.7,
    }
    payload.update(overrides)
    return payload


def test_refusal_round_trips_with_all_mutation_fields_empty():
    result = Recommendation.model_validate(
        _minimal_recommendation(
            recommendation_type="refusal",
            explanation="I can only help with this mix and Studio controls.",
        )
    )
    assert result.recommendation_type == "refusal"
    assert result.proposed_order is None
    assert result.removed_item_ids == []
    assert result.add_item is None
    assert result.discovery_results == []
    assert result.suggested_action is None


@pytest.mark.parametrize(
    "field, value",
    [
        ("proposed_order", [1, 2]),
        ("transition_changes", [{"item_id": 1, "transition_type": "cut", "duration_ms": 0}]),
        ("segment_bound_change", {"candidate_id": 1, "proposed_start_ms": 0, "proposed_end_ms": 1000}),
        ("removed_item_ids", [1]),
        (
            "add_item",
            {"source_type": "saved_segment", "saved_segment_id": 1, "insert_after_item_id": None},
        ),
        ("suggested_action", "render_mix"),
    ],
)
def test_refusal_rejects_any_mutation_or_action_field(field, value):
    with pytest.raises(ValidationError, match="A refusal may not include"):
        Recommendation.model_validate(
            _minimal_recommendation(recommendation_type="refusal", **{field: value})
        )


def test_add_item_requires_exactly_one_source():
    # Neither source set.
    with pytest.raises(ValidationError):
        AddItem.model_validate({"source_type": "catalog"})
    # Both sources set.
    with pytest.raises(ValidationError):
        AddItem.model_validate(
            {
                "source_type": "catalog",
                "source_track_id": "42",
                "saved_segment_id": 3,
                "start_ms": 0,
                "end_ms": 1000,
            }
        )
    # A new catalog/audius segment without bounds.
    with pytest.raises(ValidationError):
        AddItem.model_validate({"source_type": "audius", "source_track_id": "abc"})
    # Valid saved_segment reference.
    saved = AddItem.model_validate({"source_type": "saved_segment", "saved_segment_id": 5})
    assert saved.saved_segment_id == 5
    # Valid new-segment reference.
    fresh = AddItem.model_validate(
        {"source_type": "catalog", "source_track_id": "42", "start_ms": 0, "end_ms": 5000}
    )
    assert fresh.source_track_id == "42"


def test_removed_item_ids_respects_max_five_cap():
    with pytest.raises(ValidationError):
        Recommendation.model_validate(
            _minimal_recommendation(
                recommendation_type="plan",
                removed_item_ids=[1, 2, 3, 4, 5, 6],
            )
        )
    ok = Recommendation.model_validate(
        _minimal_recommendation(recommendation_type="plan", removed_item_ids=[1, 2, 3, 4, 5])
    )
    assert ok.removed_item_ids == [1, 2, 3, 4, 5]


def test_discovery_results_round_trip_with_reason():
    result = Recommendation.model_validate(
        _minimal_recommendation(
            discovery_results=[
                {
                    "source_type": "audius",
                    "source_track_id": "abc",
                    "title": "Track",
                    "artist": "Artist",
                    "duration_ms": 120000,
                    "reason": "matches your low-energy request",
                }
            ]
        )
    )
    assert result.discovery_results[0].reason == "matches your low-energy request"


def test_larger_schema_still_repairs_qwen_thinking_prefix(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(
        "studio_ai.main.prompt_parser._acquire_ollama_slot", lambda _timeout: lambda: None
    )
    monkeypatch.setattr("studio_ai.main.prompt_parser._record_ollama_call", lambda *_: None)

    plan = _plan()
    plan["removed_item_ids"] = [12]
    plan["add_item"] = None
    plan["discovery_results"] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"' + json.dumps(plan)}}

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
    assert response.status_code == 200
    assert response.json()["removed_item_ids"] == [12]
