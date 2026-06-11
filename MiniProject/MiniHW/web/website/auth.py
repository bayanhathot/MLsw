from flask import Blueprint, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

from .utils import (
    error_response,
    increment_success,
    increment_fail,
    get_authenticated_user,
    get_json_body,
    validate_username_password,
)

auth = Blueprint("auth", __name__)


@auth.route("/register", methods=["POST"])
def register():
    data = get_json_body()

    if data is None:
        increment_fail()
        return error_response(400, "Malformed request")

    username, password = validate_username_password(data)

    if username is None or password is None:
        increment_fail()
        return error_response(400, "Malformed request")

    if username in current_app.users:
        increment_fail()
        return error_response(409, "Username already exists")

    current_app.users[username] = generate_password_hash(password)

    increment_success()
    return jsonify({
        "message": "User registered successfully"
    }), 201


@auth.route("/login", methods=["POST"])
def login():
    data = get_json_body()

    if data is None:
        increment_fail()
        return error_response(400, "Malformed request")

    username, password = validate_username_password(data)

    if username is None or password is None:
        increment_fail()
        return error_response(400, "Malformed request")

    stored_password_hash = current_app.users.get(username)

    if stored_password_hash is None:
        increment_fail()
        return error_response(401, "Invalid username or password")

    if not check_password_hash(stored_password_hash, password):
        increment_fail()
        return error_response(401, "Invalid username or password")

    token = secrets.token_hex(32)
    current_app.tokens[token] = username

    increment_success()
    return jsonify({
        "token": token
    }), 200


@auth.route("/logout", methods=["POST"])
def logout():
    token, username = get_authenticated_user()

    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    current_app.tokens.pop(token, None)

    increment_success()
    return jsonify({
        "message": "Logged out successfully"
    }), 200