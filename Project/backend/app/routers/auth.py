"""
auth.py

FastAPI routes for authentication.

Current auth design:
- Register creates a user.
- Login verifies credentials and stores JWT in an HTTP-only cookie.
- /me reads the JWT from the cookie and returns the current user.
- Logout deletes the cookie.

Why HTTP-only cookie?
The frontend JavaScript cannot read an HTTP-only cookie.
This is safer than storing the JWT in localStorage.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.rate_limit import auth_rate_limit
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, APP_ENV, decode_access_token
from app.database.database import get_db
from app.database.models.user import User
from app.schemas import UserCreate, UserLogin, UserRead
from app.services.auth_service import register_user, login_user


router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


# Cookie name used by the backend and browser.
ACCESS_TOKEN_COOKIE_NAME = "cuemix_access_token"


def _cookie_samesite() -> str:
    configured = os.getenv("COOKIE_SAMESITE", "lax").lower()
    return configured if configured in {"lax", "strict", "none"} else "lax"


def _cookie_secure() -> bool:
    configured = os.getenv("COOKIE_SECURE")
    explicitly_secure = configured is not None and configured.lower() in {"1", "true", "yes"}
    return APP_ENV == "production" or explicitly_secure or _cookie_samesite() == "none"


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency that returns the currently authenticated user.

    With HTTP-only cookie auth:
    1. Browser sends the cookie automatically.
    2. Backend reads the cookie from request.cookies.
    3. Backend decodes the JWT.
    4. Backend loads the user from PostgreSQL.
    """

    token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    user_id = decode_access_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from None

    user = db.query(User).filter(User.id == parsed_user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled.",
        )

    return user


def get_optional_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Return a user for a valid cookie; any auth failure degrades to anonymous.

    Guest-friendly endpoints must keep working for a visitor whose cookie has
    expired or gone stale rather than raising 401 in place of serving public
    content. Endpoints that require auth continue to use get_current_user
    directly, which still raises on any failure.
    """

    if request.cookies.get(ACCESS_TOKEN_COOKIE_NAME) is None:
        return None
    try:
        return get_current_user(request=request, db=db)
    except HTTPException:
        return None


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    _: None = Depends(auth_rate_limit),
    db: Session = Depends(get_db),
):
    """
    Register a new Cuemix user.

    This endpoint only creates the user.
    It does not automatically log the user in.
    """

    return register_user(db=db, user_data=user_data)


@router.post("/login")
def login(
    login_data: UserLogin,
    response: Response,
    _: None = Depends(auth_rate_limit),
    db: Session = Depends(get_db),
):
    """
    Login user and store JWT in an HTTP-only cookie.

    Old design:
        Return JWT in JSON.

    New design:
        Set JWT in HTTP-only cookie.

    This means the frontend does not need to store the token manually.
    """

    access_token = login_user(db=db, login_data=login_data)

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )

    return {
        "message": "Login successful",
    }


@router.post("/logout")
def logout(response: Response):
    """
    Logout user by deleting the auth cookie.

    Since the JWT is stored in the browser cookie,
    deleting the cookie logs the user out from the browser side.
    """

    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite=_cookie_samesite(),
    )

    return {
        "message": "Logout successful",
    }


@router.get("/me", response_model=UserRead)
def read_me(
    current_user: User = Depends(get_current_user),
):
    """
    Protected endpoint.

    Returns the user connected to the HTTP-only cookie JWT.
    """

    return current_user
