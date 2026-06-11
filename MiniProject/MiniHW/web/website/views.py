from flask import Blueprint, jsonify, current_app, request
from PIL import Image
import time
import os

from .utils import (
    error_response,
    increment_success,
    increment_fail,
    get_authenticated_user,
)

views = Blueprint("views", __name__)


@views.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "PictureServer is running"
    }), 200


@views.route("/status", methods=["GET"])
def status():
    token, username = get_authenticated_user()

    if token is None:
        return error_response(401, "Missing or invalid token")

    uptime = time.time() - current_app.start_time

    return jsonify({
        "status": {
            "uptime": uptime,
            "processed": {
                "success": current_app.stats["success"],
                "fail": current_app.stats["fail"]
            },
            "health": "ok" if current_app.model_ready else "error",
            "api_version": 1
        }
    }), 200


@views.route("/classifier", methods=["POST"])
def classifier():
    token, username = get_authenticated_user()

    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    if "image" not in request.files:
        increment_fail()
        return error_response(400, "Malformed request")

    image_file = request.files["image"]

    if image_file.filename is None or image_file.filename == "":
        increment_fail()
        return error_response(400, "Malformed request")

    filename = image_file.filename.lower()

    if not (filename.endswith(".png") or filename.endswith(".jpeg")):
        increment_fail()
        return error_response(400, "Unsupported image format")

    if image_file.mimetype not in ["image/png", "image/jpeg"]:
        increment_fail()
        return error_response(400, "Unsupported image format")

    try:
        image = Image.open(image_file.stream)
        image.verify()
    except Exception:
        increment_fail()
        return error_response(400, "Unsupported image format")

    try:
        matches = classify_image(filename)
    except Exception:
        increment_fail()
        return error_response(500, "Internal server error")

    if not valid_matches(matches):
        increment_fail()
        return error_response(500, "Internal server error")

    increment_success()
    return jsonify({
        "matches": matches
    }), 200


def classify_image(filename):
    """
    Replace this function with your real model later.

    The interface format requires:
    [
        {"name": string, "score": number}
    ]

    score must satisfy:
    0.0 < score <= 1.0
    and total score sum <= 1.0
    """

    # Temporary format-correct placeholder.
    # For final submission, connect this to a real image classification model.
    return [
        {
            "name": "unknown",
            "score": 1.0
        }
    ]


def valid_matches(matches):
    if not isinstance(matches, list):
        return False

    if len(matches) == 0:
        return False

    total_score = 0.0

    for match in matches:
        if not isinstance(match, dict):
            return False

        if set(match.keys()) != {"name", "score"}:
            return False

        name = match["name"]
        score = match["score"]

        if not isinstance(name, str):
            return False

        if not isinstance(score, (int, float)):
            return False

        if score <= 0.0 or score > 1.0:
            return False

        total_score += score

    if total_score <= 0.0 or total_score > 1.0:
        return False

    return True