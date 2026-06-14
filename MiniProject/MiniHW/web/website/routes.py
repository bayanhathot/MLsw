import threading
import time
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request, url_for
from PIL import Image

from .local_classifier import classify_image
from .utils import (
    get_cookie_token,
    get_bearer_token,
    json_error,
    record_fail,
    record_success,
    require_bearer_auth,
    require_page_login,
    username_from_token,
)

bp = Blueprint("routes", __name__)
SERVER_STARTED_AT = time.time()
CLASSIFICATION_LOCK = threading.Lock()
ALLOWED_EXTENSIONS = {".png", ".jpeg"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg"}


@bp.route("/", methods=["GET"])
def home():
    if username_from_token(get_cookie_token()):
        return redirect(url_for("routes.dashboard_page"))
    return redirect(url_for("routes.login_page"))


@bp.route("/login", methods=["GET"])
def login_page():
    is_logged_in = username_from_token(get_cookie_token()) is not None
    return render_template("login.html", title="Login", is_logged_in=is_logged_in, page="login"), 200


@bp.route("/register", methods=["GET"])
def register_page():
    is_logged_in = username_from_token(get_cookie_token()) is not None
    return render_template("register.html", title="Register", is_logged_in=is_logged_in, page="register"), 200


@bp.route("/dashboard", methods=["GET"])
@require_page_login
def dashboard_page(username):
    return render_template("dashboard.html", title="Dashboard", is_logged_in=True, username=username, page="dashboard"), 200


@bp.route("/classify", methods=["GET"])
@require_page_login
def classify_page(username):
    return render_template("classify.html", title="Classify Image", is_logged_in=True, username=username, page="classify"), 200


@bp.route("/status-page", methods=["GET"])
@require_page_login
def status_page(username):
    return render_template("status.html", title="Server Status", is_logged_in=True, username=username, page="status"), 200


@bp.route("/register", methods=["POST"])
def register_api():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        record_fail()
        return json_error("Malformed request", 400)

    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        record_fail()
        return json_error("Malformed request", 400)

    username = username.strip()
    if not username or not password:
        record_fail()
        return json_error("Malformed request", 400)

    created = current_app.extensions["users"].create_user(username, password)
    if not created:
        record_fail()
        return json_error("Username already exists", 409)

    record_success()
    return jsonify({"message": "User registered successfully"}), 201


@bp.route("/login", methods=["POST"])
def login_api():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        record_fail()
        return json_error("Malformed request", 400)

    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        record_fail()
        return json_error("Malformed request", 400)

    username = username.strip()
    if not username or not password:
        record_fail()
        return json_error("Malformed request", 400)

    if not current_app.extensions["users"].verify_user(username, password):
        record_fail()
        return json_error("Invalid username or password", 401)

    token = current_app.extensions["sessions"].create(username)
    record_success()

    response = jsonify({"token": token})
    response.set_cookie("session_token", token, httponly=True, samesite="Lax")
    return response, 200


@bp.route("/logout", methods=["POST"])
@require_bearer_auth(count_failure=True)
def logout_api(username, token):
    current_app.extensions["sessions"].invalidate(token)
    record_success()

    response = jsonify({"message": "Logged out successfully"})
    response.delete_cookie("session_token")
    return response, 200


@bp.route("/status", methods=["GET"])
@require_bearer_auth(count_failure=False)
def status_api(username, token):
    uptime = time.time() - SERVER_STARTED_AT
    return jsonify({
        "status": {
            "uptime": uptime,
            "processed": current_app.extensions["stats"].snapshot(),
            "health": "ok",
            "api_version": 1,
        }
    }), 200


@bp.route("/classifier", methods=["POST"])
@require_bearer_auth(count_failure=True)
def classifier_api(username, token):
    acquired = CLASSIFICATION_LOCK.acquire(blocking=False)
    if not acquired:
        record_fail()
        return json_error("Classifier is busy. Please try again later.", 500)

    try:
        if "image" not in request.files:
            record_fail()
            return json_error("Malformed request", 400)

        image_file = request.files["image"]
        filename = image_file.filename or ""
        extension = Path(filename).suffix.lower()
        mime_type = image_file.mimetype or ""

        if extension not in ALLOWED_EXTENSIONS:
            record_fail()
            return json_error("Unsupported image format", 400)

        # Some clients omit the per-file MIME type in multipart uploads.
        # The interface asks for PNG/JPEG, so we primarily enforce the filename
        # extension and decodability, while accepting missing/octet-stream MIME.
        if mime_type not in ALLOWED_MIME_TYPES and mime_type not in {"", "application/octet-stream"}:
            record_fail()
            return json_error("Unsupported image format", 400)

        if not mime_type or mime_type == "application/octet-stream":
            mime_type = "image/png" if extension == ".png" else "image/jpeg"

        image_bytes = image_file.read()
        if not image_bytes:
            record_fail()
            return json_error("Malformed request", 400)

        if not _is_decodable_image(image_bytes):
            record_fail()
            return json_error("Unsupported image format", 400)

        matches = classify_image(image_bytes, mime_type)
        if not _valid_matches(matches):
            record_fail()
            return json_error("Classification failed", 500)

        record_success()
        return jsonify({"matches": matches}), 200

    except Exception:
        record_fail()
        return json_error("Classification failed", 500)

    finally:
        CLASSIFICATION_LOCK.release()


@bp.route("/browser-logout", methods=["POST"])
def browser_logout():
    """Convenience route for the website menu. The formal API logout remains POST /logout."""
    token = get_bearer_token() or get_cookie_token()
    if token:
        current_app.extensions["sessions"].invalidate(token)
    response = jsonify({"message": "Logged out successfully"})
    response.delete_cookie("session_token")
    return response, 200


def _is_decodable_image(image_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            image.convert("RGB").resize((4, 4))
        return True
    except Exception:
        return False


def _valid_matches(matches) -> bool:
    if not isinstance(matches, list) or not matches:
        return False
    total = 0.0
    for match in matches:
        if not isinstance(match, dict):
            return False
        if not isinstance(match.get("name"), str) or not match["name"].strip():
            return False
        score = match.get("score")
        if not isinstance(score, (int, float)):
            return False
        if score <= 0.0 or score > 1.0:
            return False
        total += float(score)
    return 0.0 < total <= 1.0
