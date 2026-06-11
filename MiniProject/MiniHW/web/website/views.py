from flask import Blueprint, jsonify, current_app, request
import time

views = Blueprint("views", __name__)


def error_response(code, message):
    return jsonify({
        "error": {
            "http_status": code,
            "message": message
        }
    }), code


def get_bearer_token():
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer "):].strip()

    if not token:
        return None

    return token


def get_authenticated_user():
    token = get_bearer_token()

    if not token:
        return None, None

    username = current_app.tokens.get(token)

    if not username:
        return None, None

    return token, username


@views.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "PictureServer is running"
    }), 200


@views.route("/status", methods=["GET"])
def status():
    token, username = get_authenticated_user()

    if not token:
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