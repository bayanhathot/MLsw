from flask import Blueprint, jsonify, current_app, request
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

from .utils import error_response, increment_success, increment_fail

auth = Blueprint("auth", __name__)


def ensure_auth_storage():
    """
    Make sure current_app has dictionaries for users and tokens.

    users:
        username -> hashed password

    tokens:
        token -> username
    """
    if not hasattr(current_app, "users"):
        current_app.users = {}

    if not hasattr(current_app, "tokens"):
        current_app.tokens = {}


def get_json_body():
    """
    Authentication endpoints must receive JSON.

    Valid body:
        {"username": "testuser", "password": "securepassword123"}
    """
    if not request.is_json:
        return None

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return None

    return data


def validate_username_password(data):
    """
    The interface requires username and password to be strings.
    """
    username = data.get("username")
    password = data.get("password")

    # תיקון 2: וידוא אקספליציטי שהמפתחות קיימים ב-JSON
    if "username" not in data or "password" not in data:
        return None, None

    if not isinstance(username, str):
        return None, None

    if not isinstance(password, str):
        return None, None

    if username == "" or password == "":
        return None, None

    return username, password


def get_authenticated_user():
    """
    Protected endpoints must use:

        Authorization: Bearer <token>

    Returns:
        token, username

    If authentication fails:
        None, None
    """
    ensure_auth_storage()

    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return None, None

    parts = auth_header.split()

    if len(parts) != 2:
        return None, None

    scheme, token = parts

    if scheme != "Bearer":
        return None, None

    username = current_app.tokens.get(token)

    if username is None:
        return None, None

    return token, username

@auth.route("/register", methods=["POST"])
def register():
    ensure_auth_storage()

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
    ensure_auth_storage()

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
    return jsonify({
        "token": token
    }), 200


@auth.route("/logout", methods=["POST"])
def logout():
    ensure_auth_storage()

    token, username = get_authenticated_user()

    if token is None:
        increment_fail()
        return error_response(401, "Missing or invalid token")

    current_app.tokens.pop(token, None)

    increment_success()
    return jsonify({
        "message": "Logged out successfully"
    }), 200