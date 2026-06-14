"""
Integration tests.
These check that several features work together: register -> login -> protected endpoint -> logout.
"""
import uuid
import requests

BASE_URL = "http://localhost:5000"
TIMEOUT = 10


def create_user_and_login(prefix="integration"):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    password = "simple_password_123"

    register_response = requests.post(
        f"{BASE_URL}/register",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    assert register_response.status_code == 201, register_response.text

    login_response = requests.post(
        f"{BASE_URL}/login",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json().get("token")
    assert token
    return username, password, token


def test_register_login_status_logout_flow():
    username, password, token = create_user_and_login()

    status_response = requests.get(
        f"{BASE_URL}/status",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    assert status_response.status_code == 200, status_response.text
    data = status_response.json()
    assert "status" in data
    assert data["status"]["api_version"] == 1

    logout_response = requests.post(
        f"{BASE_URL}/logout",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    assert logout_response.status_code == 200, logout_response.text
    assert logout_response.json() == {"message": "Logged out successfully"}


def test_duplicate_register_after_first_register_returns_409():
    username, password, token = create_user_and_login("duplicate")

    duplicate_response = requests.post(
        f"{BASE_URL}/register",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    assert duplicate_response.status_code == 409, duplicate_response.text
    data = duplicate_response.json()
    assert data["error"]["http_status"] == 409
