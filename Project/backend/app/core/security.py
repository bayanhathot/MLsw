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

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set. Check your .env file.")

# Password hashing context.
# bcrypt is a strong password hashing algorithm.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    """
    Convert a plain password into a secure password hash.

    Example:
    "123456" -> "$2b$12$....."

    We store the hash in the database, not the real password.
    """

    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check whether a plain password matches a stored password hash.

    Used during login.
    """

    return pwd_context.verify(plain_password, hashed_password)


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

        if subject is None:
            return None

        return str(subject)

    except JWTError:
        return None