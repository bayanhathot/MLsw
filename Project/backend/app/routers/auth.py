"""
auth.py

FastAPI routes for authentication.

Endpoints:
1. POST /auth/register
2. POST /auth/login
3. GET /auth/me
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.database import get_db
from app.database.models.user import User
from app.schemas import Token, UserCreate, UserLogin, UserRead
from app.services.auth_service import register_user, login_user

# Creates a router with prefix /auth.
# All endpoints here start with /auth.
router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

# This tells FastAPI where the token is expected to come from.
# The frontend sends:
# Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency that returns the currently authenticated user.

    Steps:
    1. Read token from Authorization header.
    2. Decode token.
    3. Extract user id from token.
    4. Load user from database.
    5. Return User object.
    """

    user_id = decode_access_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()

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


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db),
):
    """
    Register a new Zonix user.

    Request body:
    {
      "username": "mrisatmo",
      "email": "mrisatmo@example.com",
      "password": "strongpassword"
    }

    Response:
    User data without password.
    """

    return register_user(db=db, user_data=user_data)


@router.post("/login", response_model=Token)
def login(
    login_data: UserLogin,
    db: Session = Depends(get_db),
):
    """
    Login an existing user.

    Request body:
    {
      "email": "mrisatmo@example.com",
      "password": "strongpassword"
    }

    Response:
    {
      "access_token": "...",
      "token_type": "bearer"
    }
    """

    access_token = login_user(db=db, login_data=login_data)

    return Token(
        access_token=access_token,
        token_type="bearer",
    )


@router.get("/me", response_model=UserRead)
def read_me(
    current_user: User = Depends(get_current_user),
):
    """
    Protected endpoint.

    Returns the user connected to the provided JWT token.

    This proves auth works.
    """

    return current_user