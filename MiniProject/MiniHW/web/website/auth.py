import secrets

from flask import Blueprint, current_app, jsonify, render_template
from werkzeug.security import check_password_hash, generate_password_hash

from .utils import (
    error_response,
    get_authenticated_user,
    get_json_body,
    increment_fail,
    increment_success,
    init_runtime_state,
    validate_username_password,
)


auth = Blueprint("auth", __name__)


@auth.route("/register", methods=["GET"])
def register_page():
    return render_template("register.html", title="Register"), 200


@auth.route("/register", methods=["POST"])
def register():
    init_runtime_state(current_app)

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
    return jsonify({"message": "User registered successfully"}), 201


@auth.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html", title="Login"), 200


@auth.route("/login", methods=["POST"])
def login():
    init_runtime_state(current_app)

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
    while token in current_app.tokens:
        token = secrets.token_hex(32)

    current_app.tokens[token] = username

    increment_success()
    return jsonify({"token": token}), 200


@auth.route("/logout", methods=["POST"])
def logout():
    init_runtime_state(current_app)

    token, username = get_authenticated_user()
    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    current_app.tokens.pop(token, None)

    increment_success()
    return jsonify({"message": "Logged out successfully"}), 200
