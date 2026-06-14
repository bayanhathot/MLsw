"""
System tests.
These simulate a complete user scenario: account creation, login, status, valid classification,
invalid classification, status again, logout, and then token should no longer work.
"""
import base64
import uuid
import requests

BASE_URL = "http://localhost:5000"
TIMEOUT = 30


import io  # הוסיפי את הייבוא הזה בראש הפונקציה או בראש הקובץ

# 1. שימוש במחרוזת בייטים אמינה ותקנית לחלוטין של PNG
VALID_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# 2. עטיפת הבייטים ב-BytesIO כדי לדמות קובץ אמיתי בזיכרון
image_stream = io.BytesIO(VALID_PNG_BYTES)

# 3. שליחת הקובץ עם שם, הסטרים, וה-MIME Type המדויק

def register_and_login():
    username = f"system_{uuid.uuid4().hex[:8]}"
    password = "simple_password_123"

    r = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=TIMEOUT)
    assert r.status_code == 201, r.text

    r = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    token = r.json().get("token")
    assert token
    return token


def assert_status_shape(response):
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data.keys()) == {"status"}
    status = data["status"]
    assert isinstance(status["uptime"], (int, float))
    assert isinstance(status["processed"]["success"], int)
    assert isinstance(status["processed"]["fail"], int)
    assert status["health"] in ["ok", "error"]
    assert status["api_version"] == 1
    return status


def test_complete_user_flow_with_classifier_success_and_failure():
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    first_status = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT)
    first_status_data = assert_status_shape(first_status)

    # 2. עטיפת הבייטים ב-BytesIO כדי לדמות קובץ אמיתי בזיכרון
    image_stream = io.BytesIO(VALID_PNG_BYTES)

    # 3. שליחת הקובץ עם שם, הסטרים, וה-MIME Type המדויק
    files = {
        "image": ("somepic.png", image_stream, "image/png")
    }

    classify_response = requests.post(
        f"{BASE_URL}/classifier",
        headers=headers,
        files=files,
        timeout=TIMEOUT
    )

    assert classify_response.status_code == 200, classify_response.text
    classify_data = classify_response.json()
    assert "matches" in classify_data
    assert isinstance(classify_data["matches"], list)
    assert len(classify_data["matches"]) >= 1

    total_score = 0.0
    for match in classify_data["matches"]:
        assert isinstance(match.get("name"), str)
        assert isinstance(match.get("score"), (int, float))
        assert 0.0 < float(match["score"]) <= 1.0
        total_score += float(match["score"])
    assert 0.0 <= total_score <= 1.0

    bad_files = {"image": ("bad.bin", b"this is not a real image", "application/octet-stream")}
    bad_response = requests.post(f"{BASE_URL}/classifier", headers=headers, files=bad_files, timeout=TIMEOUT)
    assert bad_response.status_code == 400, bad_response.text
    assert bad_response.json()["error"]["http_status"] == 400

    second_status = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT)
    second_status_data = assert_status_shape(second_status)
    assert second_status_data["processed"]["success"] >= first_status_data["processed"]["success"] + 1
    assert second_status_data["processed"]["fail"] >= first_status_data["processed"]["fail"] + 1

    logout_response = requests.post(f"{BASE_URL}/logout", headers=headers, timeout=TIMEOUT)
    assert logout_response.status_code == 200, logout_response.text

    after_logout_status = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT)
    assert after_logout_status.status_code == 401, after_logout_status.text
