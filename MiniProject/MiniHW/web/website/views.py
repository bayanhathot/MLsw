from flask import Blueprint, jsonify, current_app, request
from PIL import Image
from google import genai
from google.genai import types

import os
import json
import time

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
            "api_version": 1,            
        }
    }), 200

@views.route("/classifier", methods=["POST"])
def classifier():
    # Step 1: Authentication
    token, username = get_authenticated_user()

    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    # Step 2: Check that image field exists
    if "image" not in request.files:
        increment_fail()
        return error_response(400, "Malformed request")

    image_file = request.files["image"]

    if image_file.filename is None or image_file.filename == "":
        increment_fail()
        return error_response(400, "Malformed request")

    filename = image_file.filename.lower()

    # Interface supports only .png and .jpeg
    if filename.endswith(".png"):
        mime_type = "image/png"
    elif filename.endswith(".jpeg"):
        mime_type = "image/jpeg"
    else:
        increment_fail()
        return error_response(400, "Unsupported image format")

    # Step 3: Check that the payload is a real readable image
    try:
        img = Image.open(image_file.stream)
        img.verify()
        image_file.stream.seek(0)
        image_bytes = image_file.read()
    except Exception:
        increment_fail()
        return error_response(400, "Unsupported image format")

    # Step 4: Get Gemini API key
    api_key = os.environ.get("GEMINI_API_KEY")

    if api_key is None or api_key == "":
        increment_fail()
        return error_response(500, "Gemini API key is missing")

    # Step 5: Ask Gemini to classify the image
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
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                ),
                prompt
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        result = json.loads(response.text)

    except Exception:
        increment_fail()
        return error_response(500, "Classification failed")

    # Step 6: Validate Gemini response before returning it
    if not isinstance(result, dict):
        increment_fail()
        return error_response(500, "Invalid classifier response")

    matches = result.get("matches")

    if not isinstance(matches, list) or len(matches) == 0:
        increment_fail()
        return error_response(500, "Invalid classifier response")

    clean_matches = []
    total_score = 0.0

    for match in matches[:3]:
        if not isinstance(match, dict):
            continue

        name = match.get("name")
        score = match.get("score")

        if not isinstance(name, str):
            continue

        if not isinstance(score, (int, float)):
            continue

        score = float(score)

        if score <= 0.0 or score > 1.0:
            continue

        clean_matches.append({
            "name": name.strip().lower(),
            "score": score
        })

        total_score += score

    if len(clean_matches) == 0:
        increment_fail()
        return error_response(500, "Invalid classifier response")

    # Make sure total score does not exceed 1.0
    if total_score > 1.0:
        for match in clean_matches:
            match["score"] = match["score"] / total_score

    increment_success()
    return jsonify({
        "matches": clean_matches
    }), 200