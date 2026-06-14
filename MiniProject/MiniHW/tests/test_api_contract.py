import io
import uuid

import pytest
import requests
from PIL import Image

BASE_URL = "http://localhost:5000"


def make_png_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), color=(220, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def unique_user():
    return f"student_{uuid.uuid4().hex[:10]}", "password_123"


def register_and_login():
    username, password = unique_user()
    response = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 201, response.text
    response = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    return token


def test_register_endpoint_success():
    username, password = unique_user()
    response = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 201
    assert response.json() == {"message": "User registered successfully"}


def test_register_duplicate_conflict():
    username, password = unique_user()
    response = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 201
    response = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 409
    assert response.json()["error"]["http_status"] == 409


def test_login_endpoint_returns_token():
    username, password = unique_user()
    requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    response = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 200
    assert isinstance(response.json().get("token"), str)


def test_status_endpoint_requires_token():
    response = requests.get(f"{BASE_URL}/status", timeout=10)
    assert response.status_code == 401
    assert response.json()["error"]["http_status"] == 401


def test_status_endpoint_shape():
    token = register_and_login()
    response = requests.get(f"{BASE_URL}/status", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert response.status_code == 200
    body = response.json()
    assert body["status"]["api_version"] == 1
    assert body["status"]["health"] in {"ok", "error"}
    assert isinstance(body["status"]["uptime"], (int, float))
    assert set(body["status"]["processed"].keys()) == {"success", "fail"}


def test_classifier_valid_png_response_shape():
    token = register_and_login()
    files = {"image": ("sample.png", make_png_bytes(), "image/png")}
    response = requests.post(
        f"{BASE_URL}/classifier",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        timeout=20,
    )
    assert response.status_code == 200, response.text
    matches = response.json().get("matches")
    assert isinstance(matches, list) and len(matches) >= 1
    assert 0 < sum(match["score"] for match in matches) <= 1
    for match in matches:
        assert isinstance(match["name"], str)
        assert 0.0 < match["score"] <= 1.0


def test_classifier_rejects_invalid_file():
    token = register_and_login()
    files = {"image": ("bad.bin", b"not an image", "application/octet-stream")}
    response = requests.post(
        f"{BASE_URL}/classifier",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        timeout=10,
    )
    assert response.status_code == 400
    assert response.json()["error"]["http_status"] == 400


def test_logout_endpoint_invalidates_token():
    token = register_and_login()
    response = requests.post(f"{BASE_URL}/logout", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert response.status_code == 200
    assert response.json() == {"message": "Logged out successfully"}
    response = requests.get(f"{BASE_URL}/status", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert response.status_code == 401
