import json

import pytest
from studio_ai import deployment_gate


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return json.dumps(self._payload).encode("utf-8")


def _plan(**overrides):
    plan = {
        "recommendation_type": "plan",
        "base_revision": 1,
        "remembered_constraints": [],
        "proposed_order": [12, 11],
        "transition_changes": [
            {"item_id": 12, "transition_type": "crossfade", "duration_ms": 4000}
        ],
        "segment_bound_change": None,
        "calculations": None,
        "warnings": [],
        "reason_tags": ["deployment-gate"],
        "explanation": "The requested order and crossfade are ready for review.",
        "confidence": 0.9,
        "requires_user_confirmation": True,
    }
    plan.update(overrides)
    return plan


def _fake_urlopen(responses, calls):
    queue = iter(responses)

    def fake(request, *, timeout):
        calls.append((request, timeout))
        return _Response(next(queue))

    return fake


def test_gate_checks_readiness_and_completes_real_plan(monkeypatch):
    calls = []
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("STUDIO_AI_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setenv("STUDIO_AI_DEPLOYMENT_GATE_TIMEOUT_SECONDS", "250")
    monkeypatch.setattr(
        deployment_gate,
        "urlopen",
        _fake_urlopen(
            [
                {"status": "ready", "model": "qwen3:8b"},
                _plan(),
            ],
            calls,
        ),
    )
    times = iter([10.0, 12.5])
    monkeypatch.setattr(deployment_gate, "perf_counter", lambda: next(times))

    assert deployment_gate.verify_local_planning_model() == 2.5
    assert calls[0] == (f"{deployment_gate.SERVICE_URL}/ready", 5.0)
    planning_request, planning_timeout = calls[1]
    assert planning_request.full_url.endswith("/internal/studio-ai/chat")
    assert planning_request.get_header("X-studio-ai-token") == "test-secret"
    assert planning_timeout == 250
    assert json.loads(planning_request.data)["context"]["mix"]["revision"] == 1


@pytest.mark.parametrize(
    "plan, message",
    [
        (_plan(recommendation_type="explanation"), "without a planning result"),
        (_plan(requires_user_confirmation=False), "bypasses user confirmation"),
        (_plan(proposed_order=[11, 12]), "requested track order"),
        (_plan(transition_changes=[]), "requested crossfade"),
    ],
)
def test_gate_rejects_non_actionable_or_unsafe_results(monkeypatch, plan, message):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setattr(
        deployment_gate,
        "urlopen",
        _fake_urlopen(
            [{"status": "ready", "model": "qwen3:8b"}, plan],
            [],
        ),
    )

    with pytest.raises(RuntimeError, match=message):
        deployment_gate.verify_local_planning_model()


def test_gate_rejects_wrong_ready_model_before_planning(monkeypatch):
    calls = []
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setattr(
        deployment_gate,
        "urlopen",
        _fake_urlopen([{"status": "ready", "model": "other:latest"}], calls),
    )

    with pytest.raises(RuntimeError, match="expected 'qwen3:8b'"):
        deployment_gate.verify_local_planning_model()
    assert len(calls) == 1


def test_gate_rejects_plan_that_exceeds_production_timeout(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("STUDIO_AI_DEPLOYMENT_GATE_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(
        deployment_gate,
        "urlopen",
        _fake_urlopen(
            [{"status": "ready", "model": "qwen3:8b"}, _plan()],
            [],
        ),
    )
    times = iter([20.0, 23.1])
    monkeypatch.setattr(deployment_gate, "perf_counter", lambda: next(times))

    with pytest.raises(RuntimeError, match="exceeding 3.00s"):
        deployment_gate.verify_local_planning_model()


def test_gate_rejects_non_positive_timeout(monkeypatch):
    monkeypatch.setenv("STUDIO_AI_DEPLOYMENT_GATE_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="must be positive"):
        deployment_gate.verify_local_planning_model()
