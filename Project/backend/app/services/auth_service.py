"""
auth_service.py

This file contains authentication business logic.

The router handles HTTP.
The service handles the actual register/login logic.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.database.models.user import User
from app.schemas import UserCreate, UserLogin


def get_user_by_email(db: Session, email: str) -> User | None:
    """
    Find a user by email.

    Returns:
        User object if found.
        None if no user exists with this email.
    """

    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    """
    Find a user by username.
    """

    return db.query(User).filter(User.username == username).first()


def register_user(db: Session, user_data: UserCreate) -> User:
    """
    Register a new user.

    Steps:
    1. Check if email already exists.
    2. Check if username already exists.
    3. Hash the password.
    4. Create User row.
    5. Commit to database.
    6. Return the created user.
    """

    existing_email_user = get_user_by_email(db, user_data.email)
    if existing_email_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered.",
        )

    existing_username_user = get_user_by_username(db, user_data.username)
    if existing_username_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken.",
        )

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


def login_user(db: Session, login_data: UserLogin) -> str:
    """
    Login user and return JWT access token.

    Steps:
    1. Find user by email.
    2. Verify password.
    3. Create access token containing user id.
    4. Return token.
    """

    user = get_user_by_email(db, login_data.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    password_is_valid = verify_password(
        plain_password=login_data.password,
        hashed_password=user.hashed_password,
    )

    if not password_is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    access_token = create_access_token(subject=str(user.id))

    return access_token