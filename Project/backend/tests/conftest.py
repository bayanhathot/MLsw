import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite://")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
# Keep the pipeline's VibeUnderstander on the deterministic parser only: the
# suite never sets OLLAMA_BASE_URL/OLLAMA_MODEL here, and tests that want to
# exercise the Ollama refinement path call prompt_parser.parse_prompt
# directly with its own env vars monkeypatched, independent of which
# provider dependencies.py wires up.
os.environ.setdefault("VIBE_LLM_PROVIDER", "none")

from app.core.rate_limit import auth_rate_limit, write_rate_limit
from app.core.redis_client import get_sync_redis_client
from app.database.base import Base
from app.database.database import get_db
from app.main import app
from app.services import audius_service, session_candidate_pool
from app.services.upload_queue import upload_queue as _upload_queue

test_engine = create_engine(
    "sqlite+pysqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(test_engine, "connect")
def enable_foreign_keys(dbapi_connection, _):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db

_ACTIVE_UPLOAD_STATUSES = {"queued", "validating", "storing", "analyzing"}


def _drain_upload_queue(timeout=15.0):
    """Wait for every job the singleton UploadQueue currently knows about to
    reach a terminal status.

    upload_queue.upload_queue's worker threads run continuously across the
    *whole* test session, independent of any single test's own lifetime --
    a test that submits a bulk-upload job and doesn't itself wait for it to
    settle (e.g. one specifically asserting that the request returns before
    completion) leaves that job's worker thread still writing to the shared
    SQLite connection *after* the test function returns. Without this, that
    write can land during the *next* test's own clean_database wipe or
    setup, corrupting it in a way that has nothing to do with what that next
    test is actually checking (observed in CI: a stray job's on_stored
    callback racing a table wipe raised a FOREIGN KEY error, and a
    completely different run saw a "duplicate registration" from a race that
    predates the fix in upload_queue.py's _run_analysis ordering). Bounded
    and non-fatal on timeout (logs to stderr rather than raising) so a
    genuinely stuck job degrades to the pre-existing flaky behavior instead
    of turning into a second hang.

    Note: this only sees real upload jobs, not submit_analysis's bare
    "analyze:<track_id>" queue entries (which are never represented in
    UploadQueue._jobs at all -- see upload_queue.py's _ANALYZE_PREFIX
    comment). That's fine here: app.main's requeue_pending_analysis(),
    the only thing that would submit one of those outside an actual
    upload's own flow, is neutralized for the whole test session below
    (a plain TestClient(app) with no `with` block, e.g. test_catalog.py's
    anonymous() helper, never runs the ASGI lifespan at all, so it was
    never actually a source of these either).
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _upload_queue._lock:
            active = [
                job_id
                for job_id, job in _upload_queue._jobs.items()
                if job["status"] in _ACTIVE_UPLOAD_STATUSES
            ]
        if not active:
            return
        time.sleep(0.02)
    print(f"conftest: _drain_upload_queue timed out after {timeout}s with jobs still active")


@pytest.fixture(autouse=True)
def clean_database(tmp_path, monkeypatch):
    # Queue workers and the serving route must share a per-test directory so
    # validation tests never write runtime media into the source tree.
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("app.routers.uploads.UPLOAD_DIR", tmp_path)
    # The catalog-track analysis job runs on a queue worker thread and opens
    # its own session (there's no per-request Depends(get_db) there); point
    # it at the same in-memory test database instead of the real one.
    monkeypatch.setattr("app.database.database.SessionLocal", TestingSessionLocal)
    # Sessions (like Mixes) try Audius first now, so every test that hits
    # POST /sessions/start would otherwise make a real network call. Default
    # it to "nothing found" so the local-catalog fallback path -- what most
    # session tests actually exercise -- is reached deterministically and
    # offline, same as before this priority swap. Tests that specifically
    # want an Audius result override this with their own later
    # monkeypatch.setattr call on the same target, which wins for that test.
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks", lambda prompt, limit=5: []
    )
    # app.main's lifespan calls requeue_pending_analysis() on every startup,
    # which fires for every `with TestClient(app) as ...` (see the client/
    # second_client/third_client fixtures below) -- i.e. potentially several
    # times per test, and via a *different* TestClient than whichever one a
    # given test is actually asserting against. That's a real production
    # feature (recovering a stranded row after a crash) with no place in a
    # suite that boots/tears down the app dozens of times per run for
    # unrelated reasons -- letting it run for real here only risks a stray
    # background analysis (reading whichever test's UPLOAD_DIR happens to be
    # monkeypatched *at the moment the worker thread gets to it*, not
    # necessarily the test that owns the row) racing some other test's own
    # assertions, for zero test value. tests/test_audio_analysis.py calls
    # audio_analysis.requeue_pending_analysis() directly (not through
    # app.main), so it's unaffected by this and still exercises the real
    # function.
    monkeypatch.setattr("app.main.requeue_pending_analysis", lambda: 0)
    # audius_service.search_tracks (the real one, wrapped separately from
    # the retriever-level monkeypatch above) caches results in module-level
    # state keyed only on (query, limit) -- tests that call it directly
    # (test_external_services.py) would otherwise leak cache entries into
    # each other across the whole run, e.g. two different tests both
    # querying "focus" at the default limit. Reset it before every test.
    audius_service._search_cache.clear()
    audius_service._last_cache_lookup["hit"] = None
    # session_candidate_pool is keyed by session_id, which is a random uuid4
    # per test so entries themselves never collide across tests -- but
    # leftover entries from earlier tests (created under the real, higher
    # SESSION_CANDIDATE_POOL_MAX_ENTRIES) skew any test that monkeypatches
    # that constant down to verify eviction behavior: put()'s one-in-one-out
    # eviction only prevents a dict from *growing* past its current limit,
    # it doesn't shrink one that was already over a newly-lowered limit.
    # Reset it before every test for the same reason as the Audius cache.
    session_candidate_pool._pools.clear()
    auth_rate_limit.reset()
    write_rate_limit.reset()
    # upload_queue.UploadQueue._recover() re-hydrates every job Redis still
    # knows about the moment *any* UploadQueue is constructed (the module
    # singleton included) -- without this, a test that builds its own queue
    # (e.g. test_uploads_rate_limit_health.py's capacity/pruning tests) would
    # recover every job every other test in this run has ever persisted to
    # the same real Redis instance, not start from an empty queue.
    redis_client = get_sync_redis_client()
    if redis_client is not None:
        for key in redis_client.scan_iter("cuemix:upload:*"):
            redis_client.delete(key)
    with TestingSessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    yield
    # Drain *here*, at this test's own teardown -- not at the next test's
    # setup. monkeypatch's own finalizer (which reverts UPLOAD_DIR and
    # SessionLocal back to production values) runs *after* this fixture's
    # teardown completes, since clean_database depends on monkeypatch. Any
    # job this test submitted but never itself waited for (e.g. a test
    # specifically asserting the request returns before completion) must
    # finish here, while this test's own patches are still the ones a
    # worker thread would see, or the straggler's write would otherwise
    # land against production config after the revert -- or, more subtly,
    # race the next test's own DB wipe/setup with whichever config happened
    # to still be in effect when the write actually landed.
    _drain_upload_queue()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def second_client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def third_client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    with TestingSessionLocal() as db:
        yield db


def register_and_login(client, username="alice", email="alice@example.com", password="strongpass"):
    response = client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client.get("/auth/me").json()
