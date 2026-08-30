"""Production-only acceptance check for the local Studio planning model.

This module runs *inside* the deployed Studio AI container.  It proves that
the service can reach the configured Ollama model and complete one real,
schema-validated planning request before the backend's production timeout.
"""

from __future__ import annotations

import json
import os
from time import perf_counter
from urllib.request import Request, urlopen

from studio_ai.schemas import Recommendation


SERVICE_URL = "http://127.0.0.1:8001"


def _timeout_seconds() -> float:
    value = float(os.getenv("STUDIO_AI_DEPLOYMENT_GATE_TIMEOUT_SECONDS", "250"))
    if value <= 0:
        raise ValueError("The deployment-gate timeout must be positive.")
    return value


def _read_json(request: str | Request, *, timeout: float) -> dict:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("Studio AI returned a non-object JSON response.")
    return payload


def verify_local_planning_model() -> float:
    """Return planning latency, or raise when the production gate must fail."""

    timeout = _timeout_seconds()
    expected_model = os.getenv("OLLAMA_MODEL", "").strip()
    readiness = _read_json(f"{SERVICE_URL}/ready", timeout=min(5.0, timeout))
    if readiness.get("status") != "ready":
        raise RuntimeError("Studio AI did not report ready status.")
    if expected_model and readiness.get("model") != expected_model:
        raise RuntimeError(
            f"Studio AI reported model {readiness.get('model')!r}; "
            f"expected {expected_model!r}."
        )

    payload = {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Create an edit plan that puts track 12 before track 11 "
                    "and uses a 4-second crossfade from track 12 into track 11."
                ),
            }
        ],
        "context": {
            "mix": {
                "revision": 1,
                "items": [
                    {
                        "item_id": 11,
                        "title": "Deployment Gate Track A",
                        "segment_start_ms": 0,
                        "segment_end_ms": 60000,
                        "bpm": 100,
                    },
                    {
                        "item_id": 12,
                        "title": "Deployment Gate Track B",
                        "segment_start_ms": 0,
                        "segment_end_ms": 60000,
                        "bpm": 104,
                    },
                ],
            }
        },
    }
    headers = {"Content-Type": "application/json"}
    internal_token = os.getenv("STUDIO_AI_INTERNAL_TOKEN", "").strip()
    if internal_token:
        headers["X-Studio-AI-Token"] = internal_token
    request = Request(
        f"{SERVICE_URL}/internal/studio-ai/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    started = perf_counter()
    result = Recommendation.model_validate(_read_json(request, timeout=timeout))
    elapsed = perf_counter() - started
    if elapsed > timeout:
        raise RuntimeError(
            f"Studio AI planning took {elapsed:.2f}s, exceeding {timeout:.2f}s."
        )
    if result.recommendation_type != "plan":
        raise RuntimeError(
            "Studio AI answered the explicit edit request without a planning result."
        )
    if not result.requires_user_confirmation:
        raise RuntimeError("Studio AI returned a plan that bypasses user confirmation.")
    if result.base_revision != 1:
        raise RuntimeError("Studio AI plan did not preserve the authoritative revision.")
    if result.proposed_order != [12, 11]:
        raise RuntimeError("Studio AI plan did not produce the requested track order.")
    expected_crossfade = any(
        change.item_id == 12
        and change.transition_type == "crossfade"
        and change.duration_ms == 4000
        for change in result.transition_changes
    )
    if not expected_crossfade:
        raise RuntimeError("Studio AI plan did not produce the requested crossfade.")
    return elapsed


def main() -> None:
    elapsed = verify_local_planning_model()
    model = os.getenv("OLLAMA_MODEL", "<unset>")
    print(f"Verified real Studio AI plan with {model} in {elapsed:.2f}s.")


if __name__ == "__main__":
    main()
