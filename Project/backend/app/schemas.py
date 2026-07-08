"""
schemas.py

Pydantic schemas define the shape of request and response data.

Important:
SQLAlchemy models define database tables.
Pydantic schemas define API input/output.
"""

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """
    Request body for registering a new user.

    The frontend sends this data to POST /auth/register.

    Password note:
    bcrypt has a 72-byte password input limit.
    For this learning project, we limit passwords to 72 characters.
    """

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)


class UserLogin(BaseModel):
    """
    Request body for logging in.

    The frontend sends this data to POST /auth/login.
    """

    email: EmailStr
    password: str


class UserRead(BaseModel):
    """
    Response shape for returning user data.

    Notice:
    We do NOT return hashed_password.
    """

    id: int
    username: str
    email: EmailStr
    is_active: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    """
    Response shape for login.

    access_token:
        JWT token the frontend stores and sends with future requests.

    token_type:
        Usually "bearer".
    """

    access_token: str
    token_type: str = "bearer"