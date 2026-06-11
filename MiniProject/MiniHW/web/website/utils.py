from flask import jsonify, request, current_app


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

    parts = auth_header.split()

    if len(parts) != 2:
        return None

    if parts[0] != "Bearer":
        return None

    token = parts[1].strip()

    if not token:
        return None

    return token


def get_authenticated_user():
    token = get_bearer_token()

    if token is None:
        return None, None

    username = current_app.tokens.get(token)

    if username is None:
        return None, None

    return token, username


def get_json_body():
    if not request.is_json:
        return None

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return None

    return data


def validate_username_password(data):
    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str):
        return None, None

    if not isinstance(password, str):
        return None, None

    if not username.strip():
        return None, None

    if not password.strip():
        return None, None

    return username, password