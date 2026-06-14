import io
import uuid

import requests
from PIL import Image

BASE_URL = "http://localhost:5000"


def make_png_bytes() -> bytes:
    image = Image.new("RGB", (40, 40), color=(30, 140, 220))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_user():
    return f"interop_{uuid.uuid4().hex[:10]}", "password_123"


def auth_token():
    username, password = make_user()
    register_response = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    assert register_response.status_code == 201, register_response.text
    login_response = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password}, timeout=10)
    assert login_response.status_code == 200, login_response.text
    token = login_response.json().get("token")
    assert token
    return token


def test_interop_register_exact_success_message():
    username, password = make_user()
    response = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=10)
    assert response.status_code == 201
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.json() == {"message": "User registered successfully"}


def test_interop_login_returns_usable_bearer_token():
    token = auth_token()
    response = requests.get(f"{BASE_URL}/status", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert response.status_code == 200, response.text
    assert response.json()["status"]["api_version"] == 1


def test_interop_classifier_missing_token_is_unauthorized():
    files = {"image": ("sample.png", make_png_bytes(), "image/png")}
    response = requests.post(f"{BASE_URL}/classifier", files=files, timeout=10)
    assert response.status_code == 401
    assert response.json()["error"]["http_status"] == 401


def test_interop_classifier_rejects_non_image_payload():
    token = auth_token()
    files = {"image": ("bad.jpeg", b"this is not a decodable image", "image/jpeg")}
    response = requests.post(
        f"{BASE_URL}/classifier",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        timeout=10,
    )
    assert response.status_code == 400
    assert response.json()["error"]["http_status"] == 400


def test_interop_classifier_valid_png_matches_shape_and_scores():
    token = auth_token()
    files = {"image": ("sample.png", make_png_bytes(), "image/png")}
    response = requests.post(
        f"{BASE_URL}/classifier",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        timeout=20,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body.get("matches"), list)
    assert body["matches"]
    total_score = 0.0
    for match in body["matches"]:
        assert isinstance(match.get("name"), str)
        assert isinstance(match.get("score"), (int, float))
        assert 0.0 < match["score"] <= 1.0
        total_score += match["score"]
    assert 0.0 < total_score <= 1.0
