"""Small environment-backed application settings helpers."""

import os

DEFAULT_CORS_ORIGINS = (
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    if not raw.strip():
        return list(DEFAULT_CORS_ORIGINS)
    return [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]


def public_api_url(path: str) -> str:
    """Build a browser-facing API URL from trusted deployment settings."""

    if not path.startswith("/"):
        raise ValueError("Public API paths must start with '/'.")
    base = os.getenv(
        "BACKEND_PUBLIC_URL", os.getenv("ROOT_PATH", "/api")
    ).strip().rstrip("/")
    return f"{base}{path}" if base else path


def pipeline_debug_enabled() -> bool:
    """Explicit opt-in gate for the internal AI-DJ pipeline/Ollama debug
    panel (routers/debug.py) -- off by default, never silently on. Combined
    with requiring a logged-in user, this keeps internal system state out of
    reach of a normal visitor without inventing a new role/permission
    system."""

    return os.getenv("ENABLE_PIPELINE_DEBUG", "false").strip().lower() in {"1", "true", "yes"}
