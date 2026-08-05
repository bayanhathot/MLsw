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


####################################################################
########################################################################

######################################mixes schemas

from datetime import datetime

from pydantic import BaseModel, Field


class MixSegmentRead(BaseModel):
    id: int
    position: int
    title: str
    artist: str
    audio_url: str
    cover_url: str | None
    start_second: int
    end_second: int
    transition_to_next: str
    source: str
    source_track_id: str

    class Config:
        from_attributes = True


class MixOwnerRead(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class MixUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    cover_url: str | None = None


class MixRead(BaseModel):
    id: int
    title: str
    prompt: str
    description: str | None
    cover_url: str | None
    status: str
    created_at: datetime
    published_at: datetime | None
    segments: list[MixSegmentRead]

    class Config:
        from_attributes = True

class MixFeedItem(BaseModel):
    id: int
    title: str
    prompt: str
    description: str | None
    cover_url: str | None
    owner: MixOwnerRead
    like_count: int
    is_liked: bool
    is_saved: bool
    published_at: datetime
    segments: list[MixSegmentRead]
