"""
security.py

This file contains security-related helper functions:
1. Hash passwords.
2. Verify passwords.
3. Create JWT access tokens.
4. Decode JWT access tokens.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from jose import JWTError, jwt
from passlib.context import CryptContext

load_dotenv()

# Read JWT settings from environment variables.
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

if ALGORITHM not in {"HS256", "HS384", "HS512"}:
    raise RuntimeError("ALGORITHM must be HS256, HS384, or HS512.")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set. Check your .env file.")

APP_ENV = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower()
PLACEHOLDER_SECRETS = {
    "secret",
    "changeme",
    "change-me",
    "your-secret-key",
    "local-development-secret-replace-before-deploying",
}


def _is_placeholder_secret(value: str) -> bool:
    """Recognize example values that must never be accepted in production."""

    normalized = value.strip().lower()
    return normalized in PLACEHOLDER_SECRETS or normalized.startswith(
        ("replace-", "changeme", "your-")
    )


if APP_ENV == "production" and (
    len(SECRET_KEY) < 32
    or _is_placeholder_secret(SECRET_KEY)
):
    raise RuntimeError("SECRET_KEY must be a non-placeholder value of at least 32 characters in production.")

# Password hashing context.
# New hashes use PBKDF2-HMAC-SHA256 with OWASP's recommended work factor.
# bcrypt remains available only to verify and transparently upgrade legacy
# hashes when their owners next authenticate.
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
    pbkdf2_sha256__default_rounds=600_000,
    pbkdf2_sha256__min_rounds=600_000,
)


def hash_password(password: str) -> str:
    """
    Convert a plain password into a secure password hash.

    We store the hash in the database, not the real password.
    """

    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check whether a plain password matches a stored password hash.

    Used during login.
    """

    is_valid, _ = verify_and_update_password(plain_password, hashed_password)
    return is_valid


def verify_and_update_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """Verify a password and return a replacement for outdated hashes."""

    try:
        return pwd_context.verify_and_update(plain_password, hashed_password)
    except (TypeError, ValueError):
        # Treat corrupted/unknown hashes as invalid credentials rather than a
        # server error that leaks account state.
        return False, None


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """
    Create a signed JWT access token.

    subject:
        The identity stored inside the token.
        For us, this will usually be the user id.

    expires_delta:
        Optional custom expiration time.
    """

    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.now(timezone.utc) + expires_delta

    # JWT payload.
    # "sub" is the standard field for subject/user identity.
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
    }

    # Sign the token using SECRET_KEY.
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """
    Decode and verify a JWT token.

    Returns:
        user id as a string if token is valid.
        None if token is invalid or expired.
    """

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")

        if not isinstance(subject, str) or not subject.strip():
            return None

        return subject

    except JWTError:
        return None
