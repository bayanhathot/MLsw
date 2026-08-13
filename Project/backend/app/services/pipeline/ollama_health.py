"""Live Ollama reachability probe for the internal debug panel.

Independent of VIBE_LLM_PROVIDER: this checks whether the configured Ollama
host is actually up and which model(s) it currently has loaded in memory,
regardless of whether Ollama is the active VibeUnderstander right now. It
never raises -- every failure mode (unset config, unreachable host, bad
response) degrades to a plain "not reachable" result, the same fail-open
posture as the rest of the optional-LLM plumbing.
"""

import os

import httpx

_HEALTH_TIMEOUT_SECONDS = 2.0


def check_ollama_health() -> dict:
    base_url = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
    configured_model = os.getenv("OLLAMA_MODEL", "").strip() or None

    if not base_url:
        return {
            "configured": False,
            "reachable": False,
            "error": "OLLAMA_BASE_URL is not set.",
            "configured_model": configured_model,
            "loaded_models": [],
        }

    try:
        with httpx.Client(timeout=httpx.Timeout(_HEALTH_TIMEOUT_SECONDS)) as client:
            response = client.get(f"{base_url}/api/ps")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "configured": True,
            "reachable": False,
            "error": str(exc),
            "configured_model": configured_model,
            "loaded_models": [],
        }

    models = payload.get("models") if isinstance(payload, dict) else None
    loaded_models = [
        str(entry["name"])
        for entry in (models or [])
        if isinstance(entry, dict) and entry.get("name")
    ]
    return {
        "configured": True,
        "reachable": True,
        "error": None,
        "configured_model": configured_model,
        "loaded_models": loaded_models,
    }
