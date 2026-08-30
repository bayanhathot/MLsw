"""Live evaluation of the configured Ollama model's multi-turn math/context
reasoning -- addresses the "Local LLM Integration" requirement's Performance
bullet ("tracking complex mathematical logic without losing context").

This is deliberately decoupled from prompt_parser.py: it talks to Ollama's
/api/chat directly (a real multi-turn message array), not the single-shot
/api/generate classification call parse_prompt() makes. It needs a genuinely
live, reachable Ollama with OLLAMA_MODEL already pulled -- unlike
eval_preferences.py, this cannot be mocked without defeating its purpose, and
is NOT part of the standard `pytest` gate (see Project/README.md's
"Optional LLM and preference evaluations" section). Run it manually, or in
an environment with Ollama available:

    cd backend && python -m scripts.eval_llm_reasoning

The scripted exchange:
  1. An early turn states two tracks' BPM values.
  2. A middle turn is unrelated filler, to prove the model isn't just
     echoing the immediately-prior message.
  3. A final turn asks a question that requires both real arithmetic and
     recalling the specific numbers from turn 1.

The reply is checked two ways: numerically (a percentage is parsed out and
compared against the actual value within a tolerance) and for context
retention (the correct BPM values/track labels from turn 1 appear in the
reply, not hallucinated ones). The percentage-tempo-increase formula below
is defined independently for this eval -- transition_planner.py itself
never computes a percentage; it only compares abs(bpm_a - bpm_b) against
fixed thresholds (TEMPO_CLOSE_BPM/TEMPO_FAR_BPM) to pick a crossfade style,
so there is no existing "real" percentage calculation to reuse.
"""

import json
import os
import re
import sys
from time import perf_counter

import httpx

from app.services.pipeline.ollama_health import check_ollama_health

TRACK_A_BPM = 120
TRACK_B_BPM = 128
# Standard percentage-tempo-increase formula: (target - source) / source * 100.
EXPECTED_PERCENT = (TRACK_B_BPM - TRACK_A_BPM) / TRACK_A_BPM * 100
PERCENT_TOLERANCE = 1.0

MESSAGES = [
    {
        "role": "user",
        "content": (
            f"I'm planning a DJ transition. Track A is {TRACK_A_BPM} BPM, "
            f"track B is {TRACK_B_BPM} BPM. Just acknowledge that for now."
        ),
    },
    {
        "role": "assistant",
        "content": "Got it -- track A is 120 BPM, track B is 128 BPM.",
    },
    {
        "role": "user",
        "content": "Unrelated question first: name one genre that usually has no vocals.",
    },
    {
        "role": "assistant",
        "content": "Ambient or instrumental electronic music is a common example.",
    },
    {
        "role": "user",
        "content": (
            "Back to the transition: what percentage tempo increase does going "
            "from track A to track B require? Show the two BPM values you're "
            "using and the percentage, to one decimal place."
        ),
    },
]

_PERCENT_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")


def _extract_percentage(reply: str) -> float | None:
    matches = _PERCENT_PATTERN.findall(reply)
    if not matches:
        return None
    # The question asks for one number; the last percentage mentioned is the
    # model's final answer if it also echoed the tolerance/example figures.
    return float(matches[-1])


def _context_retained(reply: str) -> bool:
    """True only if both original BPM values appear verbatim -- catches a
    model that answers with plausible-sounding but hallucinated numbers
    (proving it lost track of the early turn) even if the percentage happens
    to be right by coincidence."""

    return str(TRACK_A_BPM) in reply and str(TRACK_B_BPM) in reply


def _call_ollama_chat(base_url: str, model: str, timeout_seconds: float) -> tuple[str, float]:
    started = perf_counter()
    with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
        response = client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": MESSAGES,
                "stream": False,
                "think": False,
            },
        )
        response.raise_for_status()
    elapsed_ms = (perf_counter() - started) * 1000
    payload = response.json()
    message = payload.get("message") if isinstance(payload, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError(f"Unexpected /api/chat response shape: {json.dumps(payload)[:500]}")
    return content, elapsed_ms


def run_eval() -> dict:
    """Returns a plain dict so both main() (a human report) and any future
    caller share one real implementation. Never raises on an unreachable/
    unconfigured Ollama -- callers must check result["ran"] before trusting
    the pass/fail fields."""

    health = check_ollama_health()
    base_url = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip()

    if not health["reachable"]:
        return {
            "ran": False,
            "reason": f"Ollama not reachable: {health['error']}",
            "health": health,
        }
    if model and health["loaded_models"] and model not in health["loaded_models"]:
        return {
            "ran": False,
            "reason": (
                f"OLLAMA_MODEL={model!r} is configured but not currently loaded "
                f"in Ollama (loaded: {health['loaded_models']}). Pull/load it first."
            ),
            "health": health,
        }
    if not base_url or not model:
        return {
            "ran": False,
            "reason": "OLLAMA_BASE_URL / OLLAMA_MODEL are not both set.",
            "health": health,
        }

    timeout_seconds = max(0.5, min(60.0, float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "10.0"))))
    try:
        reply, elapsed_ms = _call_ollama_chat(base_url, model, timeout_seconds)
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "ran": False,
            "reason": f"Ollama chat call failed: {exc}",
            "health": health,
        }

    extracted_percent = _extract_percentage(reply)
    numeric_ok = extracted_percent is not None and abs(extracted_percent - EXPECTED_PERCENT) <= PERCENT_TOLERANCE
    context_ok = _context_retained(reply)

    return {
        "ran": True,
        "model": model,
        "base_url": base_url,
        "elapsed_ms": round(elapsed_ms, 1),
        "reply": reply,
        "expected_percent": round(EXPECTED_PERCENT, 1),
        "extracted_percent": extracted_percent,
        "numeric_ok": numeric_ok,
        "context_ok": context_ok,
        "passed": numeric_ok and context_ok,
        "health": health,
    }


def main() -> int:
    result = run_eval()
    if not result["ran"]:
        print("Eval did not run.")
        print(f"Reason: {result['reason']}")
        print(f"Health probe: {result['health']}")
        return 1

    print(f"Model: {result['model']} @ {result['base_url']}")
    print(f"Round-trip latency: {result['elapsed_ms']} ms")
    print("--- Full reply ---")
    print(result["reply"])
    print("--- Checks ---")
    print(f"Expected tempo increase: {result['expected_percent']}%")
    print(f"Extracted from reply:    {result['extracted_percent']}%")
    print(f"Numeric check (within {PERCENT_TOLERANCE}%): {'PASS' if result['numeric_ok'] else 'FAIL'}")
    print(f"Context-retention check (both BPM values present): {'PASS' if result['context_ok'] else 'FAIL'}")
    print(f"Overall: {'PASS' if result['passed'] else 'FAIL'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
