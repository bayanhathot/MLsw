import base64
import io
import uuid
import requests

BASE_URL = "http://localhost:5000"
TIMEOUT = 15

# תמונת PNG תקינה בגודל 1x1 מקודדת כטקסט
VALID_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# --- פונקציות עזר לתשתית הבדיקות ---

def make_user():
    return f"interop_{uuid.uuid4().hex[:8]}", "secure_pass_123"


def auth_token():
    username, password = make_user()
    requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=TIMEOUT)
    login_response = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password},
                                   timeout=TIMEOUT)
    return login_response.json().get("token")


def assert_status_shape(response):
    assert response.status_code == 200, response.text
    data = response.json()
    assert "status" in data
    status = data["status"]
    assert isinstance(status["uptime"], (int, float))
    assert isinstance(status["processed"]["success"], int)
    assert isinstance(status["processed"]["fail"], int)
    assert status["health"] in ["ok", "error"]
    assert status["api_version"] == 1
    return status


# --- 5 הטסטים המנצחים והחזקים ---

# 1. טסט אבטחה קשוח: הגנה על מונים ואימות פורמט Bearer (קוד 401)
def test_interop_status_requires_strict_bearer_token():
    r1 = requests.get(f"{BASE_URL}/status", timeout=TIMEOUT)
    assert r1.status_code == 401
    assert r1.json()["error"]["http_status"] == 401

    token = auth_token()
    r2 = requests.get(f"{BASE_URL}/status", headers={"Authorization": token}, timeout=TIMEOUT)
    assert r2.status_code == 401
    assert r2.json()["error"]["http_status"] == 401


# 2. טסט חוסן רישום: מניעת כפילויות משתמשים במערכת (קוד 409)
def test_interop_register_duplicate_username_returns_409():
    username, password = make_user()

    first_reg = requests.post(f"{BASE_URL}/register", json={"username": username, "password": password},
                              timeout=TIMEOUT)
    assert first_reg.status_code == 201

    second_reg = requests.post(f"{BASE_URL}/register",
                               json={"username": username, "password": "different_password_456"}, timeout=TIMEOUT)
    assert second_reg.status_code == 409, "Server should prevent duplicate usernames"
    assert second_reg.json()["error"]["http_status"] == 409


# 3. טסט זרימה מלאה: סימולציית משתמש מקצה לקצה (Happy Flow + מחיקת טוקן)
def test_interop_complete_user_flow_integration():
    # רישום והתחברות מובנים עם פונקציית העזר
    username, password = make_user()
    requests.post(f"{BASE_URL}/register", json={"username": username, "password": password}, timeout=TIMEOUT)
    login_res = requests.post(f"{BASE_URL}/login", json={"username": username, "password": password}, timeout=TIMEOUT)
    token = login_res.json().get("token")

    headers = {"Authorization": f"Bearer {token}"}

    # בדיקת סטטוס תקינה
    first_status = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT)
    assert_status_shape(first_status)

    # שליחת קובץ תקין
    image_stream = io.BytesIO(VALID_PNG_BYTES)
    files = {"image": ("somepic.png", image_stream, "image/png")}
    classify_response = requests.post(f"{BASE_URL}/classifier", headers=headers, files=files, timeout=TIMEOUT)
    assert classify_response.status_code == 200, classify_response.text

    # התנתקות ומחיקת טוקן
    logout_response = requests.post(f"{BASE_URL}/logout", headers=headers, timeout=TIMEOUT)
    assert logout_response.status_code == 200, logout_response.text

    # וידוא שהטוקן נמחק ולא תקף יותר
    after_logout_status = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT)
    assert after_logout_status.status_code == 401, after_logout_status.text


# 4. טסט לוגיקת מונים (Metrics): בדיקה שמונה ה-Fail אכן עולה בעקבות דחייה
def test_interop_classifier_increments_fail_counter_on_bad_request():
    token = auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    # שלב א': שמירת המצב הנוכחי של המונים בשרת
    status_before = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT).json()
    fails_before = status_before["status"]["processed"]["fail"]

    # שלב ב': שליחת בקשה פגומה במכוון כדי להכשיל את השרת
    bad_files = {"image": ("malformed.png", io.BytesIO(b"corrupted data"), "image/png")}
    requests.post(f"{BASE_URL}/classifier", headers=headers, files=bad_files, timeout=TIMEOUT)

    # שלב ג': וידוא שמונה ה-fail עלה ב-1 לפחות
    status_after = requests.get(f"{BASE_URL}/status", headers=headers, timeout=TIMEOUT).json()
    fails_after = status_after["status"]["processed"]["fail"]

    assert fails_after >= fails_before + 1, "The 'fail' metrics counter must increment when a request is rejected with 400"


# 5. טסט המסווג התקין: בדיקת הזרם ומבנה הנתונים האוניברסלי (קוד 200)
def test_interop_classifier_valid_flow_and_response_shape():
    token = auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    image_stream = io.BytesIO(VALID_PNG_BYTES)

    # שליחת תמונת PNG בינארית תקינה לחלוטין
    files = {"image": ("test_pic.png", image_stream, "image/png")}
    response = requests.post(f"{BASE_URL}/classifier", headers=headers, files=files, timeout=TIMEOUT)

    assert response.status_code == 200, response.text
    body = response.json()

    # וידוא מבנה ה-JSON המדויק מול דרישות המפרט
    assert "matches" in body, "Response must contain 'matches' key"
    assert isinstance(body["matches"], list), "'matches' must be a JSON array"
    assert len(body["matches"]) >= 1, "Array should contain at least one classification match"

    total_score = 0.0
    for match in body["matches"]:
        assert isinstance(match.get("name"), str), "Each match must have a text 'name'"
        assert isinstance(match.get("score"), (int, float)), "Each match must have a numerical 'score'"
        assert 0.0 < float(match["score"]) <= 1.0, "Score value must be bounded between 0.0 and 1.0"
        total_score += float(match["score"])

    assert 0.0 < total_score <= 1.0, "The cumulative sum of prediction scores must not exceed 1.0"