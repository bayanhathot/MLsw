"""
Security tests.
These try to access protected resources without a valid token.
"""
import uuid
import requests

BASE_URL = "http://localhost:5000"
TIMEOUT = 10


def assert_unauthorized(response):
    assert response.status_code == 401, response.text
    data = response.json()
    assert data["error"]["http_status"] == 401
    assert isinstance(data["error"].get("message"), str)


def test_status_rejects_missing_token():
    response = requests.get(f"{BASE_URL}/status", timeout=TIMEOUT)
    assert_unauthorized(response)


def test_status_rejects_fake_token():
    response = requests.get(
        f"{BASE_URL}/status",
        headers={"Authorization": "Bearer fake_token"},
        timeout=TIMEOUT,
    )
    assert_unauthorized(response)


def test_classifier_rejects_fake_token():
    files = {"image": ("somepic.png", b"fake", "image/png")}
    response = requests.post(
        f"{BASE_URL}/classifier",
        headers={"Authorization": "Bearer fake_token"},
        files=files,
        timeout=TIMEOUT,
    )
    assert_unauthorized(response)


def test_logout_invalidates_token():
    username = f"security_{uuid.uuid4().hex[:8]}"
    password = "simple_password_123"

    requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=TIMEOUT)
    login_response = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password}, timeout=TIMEOUT)
    token = login_response.json().get("token")
    assert token

    headers = {"Authorization": f"Bearer {token}"}
    logout_response = requests.post(f"{BASE_URL}/logout", headers=headers, timeout=TIMEOUT)
    assert logout_response.status_code == 200, logout_response.text

    status_response = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT)
    assert_unauthorized(status_response)
