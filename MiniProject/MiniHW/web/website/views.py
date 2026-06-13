from flask import Blueprint, jsonify, current_app, request
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

