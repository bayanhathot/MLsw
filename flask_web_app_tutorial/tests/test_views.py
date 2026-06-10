import pytest
import requests

SERVER_HOST = "localhost"
PORT = 5000


def base_url():
    return f"http://{SERVER_HOST}:{PORT}"


def test_status_page():
    response = requests.get(f"{base_url()}/status", timeout=10)

    assert response.status_code == 200

    data = response.json()

    assert data["version"] == "1.0"
    assert data["status"] == "OK"


def test_secret_page():
    response = requests.get(f"{base_url()}/secret", timeout=10)

    assert response.status_code == 401

    data = response.json()

    assert data["error"]["http_status"] == 401
    assert data["error"]["message"] == "You are not logged in"