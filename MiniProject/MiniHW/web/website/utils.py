from functools import wraps
from typing import Optional

from flask import current_app, jsonify, redirect, request, url_for

COUNTED_ENDPOINTS = {"/register", "/login", "/logout", "/classifier"}


def json_error(message: str, http_status: int):
    response = jsonify({
        "error": {
            "http_status": http_status,
            "message": message,
        }
    })
    response.status_code = http_status
    return response


def should_count_endpoint_failure() -> bool:
    return request.path in COUNTED_ENDPOINTS


def record_success() -> None:
    current_app.extensions["stats"].increment_success()


def record_fail() -> None:
    current_app.extensions["stats"].increment_fail()


def get_bearer_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    parts = header.split()
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def get_cookie_token() -> Optional[str]:
    return request.cookies.get("session_token")


def username_from_token(token: Optional[str]) -> Optional[str]:
    return current_app.extensions["sessions"].get_username(token)


def require_bearer_auth(count_failure: bool = True):
    """Decorator for protected API endpoints. It only accepts Authorization: Bearer."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            token = get_bearer_token()
            username = username_from_token(token)
            if not username:
                if count_failure:
                    record_fail()
                return json_error("Missing or invalid token", 401)
            return view_func(username=username, token=token, *args, **kwargs)

        return wrapper

    return decorator


def require_page_login(view_func):
    """Decorator for browser pages. Uses the session cookie set after login."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        username = username_from_token(get_cookie_token())
        if not username:
            return redirect(url_for("routes.login_page"))
        return view_func(username=username, *args, **kwargs)

    return wrapper
