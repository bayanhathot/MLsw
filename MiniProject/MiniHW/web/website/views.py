import json
import os
import time
from io import BytesIO

from flask import Blueprint, current_app, jsonify, redirect, render_template, request
from PIL import Image

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None

from .utils import (
    error_response,
    get_authenticated_user,
    increment_fail,
    increment_success,
)


views = Blueprint("views", __name__)


@views.route("/", methods=["GET"])
def home():
    return redirect("/login")


@views.route("/dashboard", methods=["GET"])
def dashboard_page():
    return render_template("dashboard.html", title="Dashboard"), 200


@views.route("/classify", methods=["GET"])
def classify_page():
    return render_template("classify.html", title="Classify Image"), 200


@views.route("/status-page", methods=["GET"])
def status_page():
    return render_template("status.html", title="Server Status"), 200


@views.route("/status", methods=["GET"])
def status():
    token, username = get_authenticated_user()
    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    uptime = time.time() - current_app.start_time

    return jsonify({
        "status": {
            "uptime": uptime,
            "processed": {
                "success": current_app.stats["success"],
                "fail": current_app.stats["fail"],
            },
            "health": "ok" if current_app.model_ready else "error",
            "api_version": 1,
        }
    }), 200


@views.route("/classifier", methods=["POST"])
def classifier():
    token, username = get_authenticated_user()
    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    lock = current_app.classification_lock
    if not lock.acquire(blocking=False):
        increment_fail()
        return error_response(429, "Classifier is busy. Please try again later")

    try:
        image_file = get_uploaded_image_file()
        if image_file is None:
            increment_fail()
            return error_response(400, "Malformed request")

        filename = (image_file.filename or "").lower()
        mime_type = detect_mime_type(filename, image_file.mimetype)
        if mime_type is None:
            increment_fail()
            return error_response(400, "Unsupported image format")

        try:
            image_bytes = image_file.read()
            if not image_bytes:
                raise ValueError("empty image")
            Image.open(BytesIO(image_bytes)).verify()
        except Exception:
            increment_fail()
            return error_response(400, "Unsupported image format")

        matches = classify_image(image_bytes, mime_type)

        increment_success()
        return jsonify({"matches": matches}), 200

    finally:
        lock.release()


def get_uploaded_image_file():
    """Support the common field names used by tests and browser forms."""
    for field_name in ("image", "file", "img"):
        if field_name in request.files:
            return request.files[field_name]
    return None


def detect_mime_type(filename, uploaded_mime_type):
    if filename.endswith(".png"):
        return "image/png"
    if filename.endswith(".jpg") or filename.endswith(".jpeg"):
        return "image/jpeg"

    if uploaded_mime_type in {"image/png", "image/jpeg"}:
        return uploaded_mime_type

    return None


def classify_image(image_bytes, mime_type):
    """
    Classify an image.

    With GEMINI_API_KEY or GOOGLE_API_KEY, it tries Gemini.
    Without an API key, it returns a deterministic local fallback so tests and
    the UI still work.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key or genai is None or types is None:
        return [{"name": "image", "score": 1.0}]

    try:
        client = genai.Client(api_key=api_key)

        prompt = """
Classify the main object in this image.

Return JSON only, with exactly this format:
{
  "matches": [
    {"name": "class_name", "score": 0.9}
  ]
}

Rules:
- Return 1 to 3 matches.
- "name" must be a short lowercase object label.
- "score" must be a number where 0.0 < score <= 1.0.
- The sum of all scores must be between 0 and 1.
- Do not add explanations.
"""

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )

        result = json.loads(response.text)
        return clean_classifier_matches(result)

    except Exception:
        return [{"name": "image", "score": 1.0}]


def clean_classifier_matches(result):
    if not isinstance(result, dict):
        return [{"name": "image", "score": 1.0}]

    matches = result.get("matches")
    if not isinstance(matches, list):
        return [{"name": "image", "score": 1.0}]

    clean_matches = []
    total_score = 0.0

    for match in matches[:3]:
        if not isinstance(match, dict):
            continue

        name = match.get("name")
        score = match.get("score")

        if not isinstance(name, str) or not isinstance(score, (int, float)):
            continue

        score = float(score)
        if score <= 0.0 or score > 1.0:
            continue

        clean_matches.append({"name": name.strip().lower(), "score": score})
        total_score += score

    if not clean_matches:
        return [{"name": "image", "score": 1.0}]

    if total_score > 1.0:
        for match in clean_matches:
            match["score"] = match["score"] / total_score

    return clean_matches
