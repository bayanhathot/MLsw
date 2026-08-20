"""
main.py

Entry point of the FastAPI backend.

This file is responsible for:
1. Creating the FastAPI app object.
2. Registering routers, such as the auth router.
3. Defining basic health-check endpoints.
4. Defining the database health-check endpoint.

Domain routers provide auth, sessions, mixes, forum, profiles, messaging,
notifications, and uploads. This module also exposes liveness, readiness, and
selector-information endpoints.
"""

import os
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

# Must run before anything transitively imports librosa/numba (both are
# lazy-imported inside audio_analysis.analyze_audio, never at module import
# time, so this is early enough). Overrides the Dockerfile's shared
# NUMBA_CACHE_DIR=/tmp/numba_cache with a per-process path: a separate
# process reading a *different* process's on-disk numba cache for the same
# @jit(cache=True) function was reproduced crashing hard (SIGSEGV, RIP=0 --
# a call through a stale/invalid compiled-function pointer), even though
# concurrent threads within one process safely race the same first-compile
# with no crash. This container's own BACKEND_WORKERS=1 (see
# docker-compose.prod.yml) makes that specific cross-process path currently
# unreachable in normal operation, but it costs nothing to close off
# entirely rather than depend on that staying true.
os.environ["NUMBA_CACHE_DIR"] = os.path.join(
    os.environ.get("NUMBA_CACHE_DIR", "/tmp/numba_cache"), str(os.getpid())
)

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.core.config import cors_origins
from app.core.redis_client import check_redis_health
from app.routers.auth import router as auth_router
from app.routers.catalog import router as catalog_router
from app.routers.media import router as media_router
from app.routers.sessions import router as sessions_router
from app.routers.mixes import router as mixes_router
from app.routers.forum import router as forum_router
from app.routers.messaging import router as messaging_router
from app.routers.listening import router as listening_router
from app.routers.profiles import router as profiles_router
from app.routers.uploads import router as uploads_router
from app.routers.social import router as social_router
from app.routers.debug import router as debug_router
from app.routers.admin_debug import router as admin_debug_router
from app.routers.realtime import router as realtime_router
from app.services.audio_analysis import requeue_pending_analysis, requeue_pending_external_analysis
from app.services.channel_hub import channel_hub

# No logging.basicConfig/dictConfig existed anywhere in this backend before
# this line -- every logger.info(...) call in app/ (including this file's
# own access_logger below) was silently swallowed: Python's root logger
# defaults to WARNING with no handler attached, and uvicorn's own default
# LOGGING_CONFIG only touches the uvicorn/uvicorn.access/uvicorn.error
# loggers, never the root or any app.*/cuemix.* logger. Only .warning/
# .error/.exception calls were ever actually visible (via logging's
# lastResort fallback handler). LOG_LEVEL is env-overridable so INFO-level
# per-stage latency logging (session_manager.py) can be dialed down in a
# noisy environment without a code change.
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

# ---------------------------------------------------------
# Create FastAPI app
# ---------------------------------------------------------
# This object is what Uvicorn runs from the Dockerfile.
#
# In the Dockerfile, we run:
# uvicorn app.main:app --host 0.0.0.0 --port 5000
#
# Meaning:
# app.main -> this file: backend/app/main.py
# app      -> this FastAPI object below
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await channel_hub.start_listener()
    # Re-dispatches analysis for any catalog track stranded at
    # analysis_status="pending" by a previous crash/restart -- see
    # requeue_pending_analysis's own docstring for why a plain "was it
    # still pending" check is sufficient here. Synchronous DB work, but
    # small/infrequent (only ever non-empty right after an unclean
    # shutdown) and startup-blocking is the right trade-off: the
    # alternative (fire-and-forget in the background) risks a request
    # racing a still-in-progress requeue.
    requeue_pending_analysis()
    # External-track counterpart (a no-op query when AUDIUS_ANALYSIS_CACHE_ENABLED
    # is False) -- see requeue_pending_external_analysis's own docstring for
    # the crash/restart gap this closes.
    requeue_pending_external_analysis()
    yield
    await channel_hub.stop_listener()


app = FastAPI(
    title="Cuemix Backend",
    description="Backend API for the Cuemix Smart AI DJ Mixer project.",
    version="0.2.0",
    root_path=os.getenv("ROOT_PATH", ""),
    lifespan=_lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).resolve().parent / "static"),
    name="static",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

access_logger = logging.getLogger("cuemix.access")


@app.middleware("http")
async def csrf_origin_guard(request, call_next):
    """Reject cross-site cookie-authenticated writes without changing the UI contract."""

    unsafe = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    cookie_auth = "cuemix_access_token" in request.cookies
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    origin = (request.headers.get("origin") or "").rstrip("/")
    if unsafe and cookie_auth and (
        fetch_site == "cross-site" or (origin and origin not in cors_origins())
    ):
        return JSONResponse(status_code=403, content={"detail": "Cross-site request rejected."})
    return await call_next(request)


@app.middleware("http")
async def request_context(request, call_next):
    """Attach a request ID and emit one structured access event."""

    request_id = request.headers.get("x-request-id", "")[:100] or uuid4().hex
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    access_logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            }
        )
    )
    return response

# ---------------------------------------------------------
# Register routers
# ---------------------------------------------------------
# Routers let us split endpoints into separate files.
#
# Instead of putting register/login/me directly inside main.py,
# we keep them in:
# backend/app/routers/auth.py
#
# This keeps main.py clean and makes the project easier to grow.
app.include_router(auth_router)
app.include_router(sessions_router)

# Register mix generation endpoints.
# POST /mixes/start creates a new mix queue from Audius search results.
app.include_router(mixes_router)
app.include_router(forum_router)
app.include_router(profiles_router)
app.include_router(messaging_router)
app.include_router(listening_router)
app.include_router(uploads_router)
app.include_router(social_router)
app.include_router(catalog_router)
app.include_router(media_router)
app.include_router(debug_router)
app.include_router(admin_debug_router)
app.include_router(realtime_router)


# ---------------------------------------------------------
# Basic backend health endpoint
# ---------------------------------------------------------
@app.get("/")
def root():
    """
    Simple backend health endpoint.

    Purpose:
    Check that the FastAPI server itself is running.

    Important:
    This endpoint does NOT test PostgreSQL.
    It only proves that the backend container/app is alive.
    """

    return {
        "service": "cuemix-backend",
        "status": "running",
        "message": "Cuemix backend is running",
    }


# ---------------------------------------------------------
# Database health endpoint
# ---------------------------------------------------------
@app.get("/db-health")
async def db_health(db: Session = Depends(get_db)):
    """
    Database health-check endpoint.

    Purpose:
    Check that FastAPI can connect to PostgreSQL.

    How it works:
    1. A client sends GET /db-health.
    2. FastAPI sees db: Session = Depends(get_db).
    3. FastAPI calls get_db().
    4. get_db() opens a SQLAlchemy database session.
    5. This endpoint sends SELECT 1 to PostgreSQL.
    6. PostgreSQL returns 1.
    7. FastAPI returns a JSON response.
    8. get_db() closes the database session.

    Why SELECT 1?
    SELECT 1 is a tiny SQL query.
    It does not require any tables.
    This lets us test the database connection before creating real tables
    like users, artists, songs, and song_segments.

    Redis is included here too (fail-open, see app.core.redis_client) so a
    broken Redis connection is visible in the same place a broken Postgres
    connection would be -- but unlike Postgres, nothing depends on Redis yet,
    so an unreachable Redis never fails this endpoint's status code.
    """

    result = db.execute(text("SELECT 1")).scalar()

    return {
        "database": "connected",
        "result": result,
        "redis": await check_redis_health(),
    }


@app.get("/health")
def health():
    """Stable health-check path for containers and load balancers."""

    return {"service": "cuemix-backend", "status": "healthy", "version": app.version}


@app.get("/model-info")
def model_info():
    """Describe the configured selection implementation without overstating it."""

    provider = os.getenv("VIBE_LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "").strip()
        configured = bool(os.getenv("OLLAMA_BASE_URL", "").strip() and model)
    else:
        model = ""
        configured = False
    return {
        "selector": "deterministic-intent-v1",
        "llm_provider": provider,
        "llm_configured": configured,
        "llm_availability": "not_checked" if configured else "not_configured",
        "llm_model": model if configured else None,
        "hallucination_guard": "playable tracks must resolve from Audius or the local demo catalog",
    }
