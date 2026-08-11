from datetime import timedelta

from passlib.hash import pbkdf2_sha256

from app.core.security import (
    _is_placeholder_secret,
    create_access_token,
    decode_access_token,
    hash_password,
    pwd_context,
)
from app.database.models.user import User


def test_auth_normalizes_and_never_exposes_hash(client):
    response = client.post(
        "/auth/register",
        json={"username": "  Alice_1  ", "email": "ALICE@EXAMPLE.COM", "password": "strongpass"},
    )
    assert response.status_code == 201
    assert response.json()["username"] == "alice_1"
    assert response.json()["email"] == "alice@example.com"
    assert "hashed_password" not in response.json()
    assert client.post(
        "/auth/login", json={"email": "Alice@Example.com", "password": "strongpass"}
    ).status_code == 200
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_duplicate_and_disabled_user(client, db_session):
    payload = {"username": "alice", "email": "alice@example.com", "password": "strongpass"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409
    user = db_session.query(User).filter_by(email="alice@example.com").first()
    user.is_active = False
    db_session.commit()
    response = client.post("/auth/login", json={"email": user.email, "password": "strongpass"})
    assert response.status_code == 403


def test_malformed_and_expired_subjects_are_unauthorized(client):
    client.cookies.set("zonix_access_token", create_access_token("not-an-integer"))
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(
        "zonix_access_token", create_access_token("1", expires_delta=timedelta(seconds=-1))
    )
    assert client.get("/auth/me").status_code == 401
    assert decode_access_token("not-a-token") is None


def test_blank_and_invalid_auth_fields(client):
    response = client.post(
        "/auth/register",
        json={"username": "bad name", "email": "not-an-email", "password": "short"},
    )
    assert response.status_code == 422


def test_passwords_longer_than_legacy_bcrypt_limit_are_supported(client):
    password = "correct horse battery staple " * 3
    assert len(password.encode("utf-8")) > 72
    assert client.post(
        "/auth/register",
        json={"username": "longpass", "email": "longpass@example.com", "password": password},
    ).status_code == 201
    assert client.post(
        "/auth/login", json={"email": "longpass@example.com", "password": password}
    ).status_code == 200


def test_cross_site_cookie_authenticated_write_is_rejected(client):
    client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strongpass"},
    )
    client.post("/auth/login", json={"email": "alice@example.com", "password": "strongpass"})
    response = client.post(
        "/sessions/start",
        json={"prompt": "focus"},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_production_and_samesite_none_force_secure_cookie(monkeypatch):
    from app.routers import auth

    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setattr(auth, "APP_ENV", "production")
    assert auth._cookie_secure() is True
    monkeypatch.setenv("COOKIE_SECURE", "false")
    assert auth._cookie_secure() is True
    monkeypatch.setattr(auth, "APP_ENV", "development")
    monkeypatch.setenv("COOKIE_SAMESITE", "none")
    assert auth._cookie_secure() is True


def test_new_password_hashes_use_recommended_pbkdf2_work_factor():
    password_hash = hash_password("strongpass")
    assert pwd_context.identify(password_hash) == "pbkdf2_sha256"
    assert int(password_hash.split("$")[2]) >= 600_000


def test_login_transparently_upgrades_legacy_password_hash(client, db_session):
    response = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strongpass"},
    )
    assert response.status_code == 201

    user = db_session.query(User).filter_by(email="alice@example.com").one()
    user.hashed_password = pbkdf2_sha256.using(rounds=29_000).hash("strongpass")
    db_session.commit()
    old_hash = user.hashed_password

    assert client.post(
        "/auth/login", json={"email": user.email, "password": "strongpass"}
    ).status_code == 200
    db_session.refresh(user)
    assert user.hashed_password != old_hash
    assert int(user.hashed_password.split("$")[2]) >= 600_000


def test_production_example_secrets_are_detected():
    assert _is_placeholder_secret("replace-with-at-least-32-random-bytes")
    assert _is_placeholder_secret("your-production-secret")
    assert not _is_placeholder_secret("A-real-randomly-generated-secret-value-123")
