import json
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash


class JsonUserStore:
    """Tiny JSON-backed user store for the homework server."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, users: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(users, indent=2), encoding="utf-8")

    def create_user(self, username: str, password: str) -> bool:
        with self._lock:
            users = self._load()
            if username in users:
                return False
            users[username] = {
                "password_hash": generate_password_hash(password),
                "created_at": time.time(),
            }
            self._save(users)
            return True

    def verify_user(self, username: str, password: str) -> bool:
        with self._lock:
            users = self._load()
            user = users.get(username)
            if not user:
                return False
            return check_password_hash(user["password_hash"], password)


class SessionStore:
    """In-memory bearer token store."""

    def __init__(self):
        self._tokens = {}
        self._lock = threading.Lock()

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = {
                "username": username,
                "created_at": time.time(),
            }
        return token

    def get_username(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        with self._lock:
            entry = self._tokens.get(token)
            return entry["username"] if entry else None

    def invalidate(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            return self._tokens.pop(token, None) is not None


class ProcessedStats:
    """Thread-safe success/fail counters for the API endpoints required by interface.md."""

    def __init__(self):
        self._success = 0
        self._fail = 0
        self._lock = threading.Lock()

    def increment_success(self) -> None:
        with self._lock:
            self._success += 1

    def increment_fail(self) -> None:
        with self._lock:
            self._fail += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "success": self._success,
                "fail": self._fail,
            }
