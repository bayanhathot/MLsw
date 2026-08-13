import os

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
# suite never sets GROQ_API_KEY, and tests that want to exercise the Ollama
# refinement path call prompt_parser.parse_prompt directly with its own env
# vars monkeypatched, independent of which provider dependencies.py wires up.
os.environ.setdefault("VIBE_LLM_PROVIDER", "none")

from app.core.rate_limit import auth_rate_limit, write_rate_limit
from app.database.base import Base
from app.database.database import get_db
from app.main import app

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
    auth_rate_limit.reset()
    write_rate_limit.reset()
    with TestingSessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    yield


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
