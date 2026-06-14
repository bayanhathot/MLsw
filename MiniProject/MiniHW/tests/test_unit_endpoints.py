"""
Unit-style API tests.
These test one endpoint behavior at a time through the public HTTP API.
Run while the server is already running on localhost:5000.
"""
import uuid
import requests

BASE_URL = "http://localhost:5000"
TIMEOUT = 10


def assert_json_response(response):
    assert "application/json" in response.headers.get("Content-Type", "")
    return response.json()


def assert_error_response(response, expected_status):
    assert response.status_code == expected_status, response.text
    data = assert_json_response(response)
    assert "error" in data
    assert data["error"]["http_status"] == expected_status
    assert isinstance(data["error"].get("message"), str)


def new_user():
    return f"unit_{uuid.uuid4().hex[:8]}", "simple_password_123"


def test_register_success():
    username, password = new_user()
    response = requests.post(
        f"{BASE_URL}/register",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    assert response.status_code == 201, response.text
    data = assert_json_response(response)
    assert data == {"message": "User registered successfully"}


def test_register_malformed_missing_password():
    response = requests.post(
        f"{BASE_URL}/register",
        json={"username": "missing_password_user"},
        timeout=TIMEOUT,
    )
    assert_error_response(response, 400)


def test_login_success_returns_token():
    username, password = new_user()
    requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=TIMEOUT)

    response = requests.post(
        f"{BASE_URL}/login",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, response.text
    data = assert_json_response(response)
    assert isinstance(data.get("token"), str)
    assert data["token"]


def test_login_wrong_password_returns_401():
    username, password = new_user()
    requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=TIMEOUT)

    response = requests.post(
        f"{BASE_URL}/login",
        json={"username": username, "password": "wrong_password"},
        timeout=TIMEOUT,
    )
    assert_error_response(response, 401)


def test_logout_without_token_returns_401():
    response = requests.post(f"{BASE_URL}/logout", timeout=TIMEOUT)
    assert_error_response(response, 401)


def test_status_without_token_returns_401():
    response = requests.get(f"{BASE_URL}/status", timeout=TIMEOUT)
    assert_error_response(response, 401)


def test_classifier_without_token_returns_401():
    files = {"image": ("somepic.png", b"not really important", "image/png")}
    response = requests.post(f"{BASE_URL}/classifier", files=files, timeout=TIMEOUT)
    assert_error_response(response, 401)
