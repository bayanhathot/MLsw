from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

auth = Blueprint("auth", __name__)


def error_response(code, message):
    return jsonify({
        "error": {
            "http_status": code,
            "message": message
        }
    }), code


def increment_success():
    current_app.stats["success"] += 1


def increment_fail():
    current_app.stats["fail"] += 1


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


@auth.route("/register", methods=["POST"])
def register():
    if not request.is_json:
        increment_fail()
        return error_response(400, "Malformed request")

    data = request.get_json(silent=True)
    if not data:
        increment_fail()
        return error_response(400, "Malformed request")

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        increment_fail()
        return error_response(400, "Malformed request")

    if not username.strip() or not password.strip():
        increment_fail()
        return error_response(400, "Malformed request")

    if username in current_app.users:
        increment_fail()
        return error_response(409, "Username already exists")

    current_app.users[username] = generate_password_hash(password)
    increment_success()
    return jsonify({"message": "User registered successfully"}), 201


@auth.route("/login", methods=["POST"])
def login():
    if not request.is_json:
        increment_fail()
        return error_response(400, "Malformed request")

    data = request.get_json(silent=True)
    if not data:
        increment_fail()
        return error_response(400, "Malformed request")

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        increment_fail()
        return error_response(400, "Malformed request")

    if not username.strip() or not password.strip():
        increment_fail()
        return error_response(400, "Malformed request")

    stored_password_hash = current_app.users.get(username)
    if not stored_password_hash:
        increment_fail()
        return error_response(401, "Invalid username or password")

    if not check_password_hash(stored_password_hash, password):
        increment_fail()
        return error_response(401, "Invalid username or password")

    token = secrets.token_hex(32)
    current_app.tokens[token] = username

    increment_success()
    return jsonify({"token": token}), 200


@auth.route("/logout", methods=["POST"])
def logout():
    token, username = get_authenticated_user()

    if not token:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    current_app.tokens.pop(token, None)
    increment_success()
    return jsonify({"message": "Logged out successfully"}), 200
