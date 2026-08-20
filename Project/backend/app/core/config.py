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


def debug_dashboard_enabled() -> bool:
    """Explicit opt-in gate for the owner-only admin debug dashboard
    (routers/admin_debug.py) -- off by default, same convention as
    pipeline_debug_enabled/AUDIUS_ANALYSIS_CACHE_ENABLED, so it can be
    killed instantly without a redeploy. This flag alone is not the access
    control -- see debug_dashboard_owner_user_id below; both must pass."""

    return os.getenv("DEBUG_DASHBOARD_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def debug_dashboard_owner_user_id() -> int | None:
    """The one user ID authorized to reach the admin debug dashboard, tied
    to a specific account rather than a new role/permission system (this
    codebase's User model has no role/is_admin column at all -- see
    pipeline_debug_enabled's own comment on that same tradeoff for the
    other debug panel). None (never authorized) when unset or unparseable,
    never a silent default."""

    raw = os.getenv("DEBUG_DASHBOARD_OWNER_USER_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
