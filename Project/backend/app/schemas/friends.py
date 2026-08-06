"""
friends.py

Pydantic schemas for the friend request / friendship endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.users import UserPublic


class FriendRequestCreate(BaseModel):
    """
    Request body for POST /friends/requests.
    """

    addressee_username: str = Field(min_length=3, max_length=50)


class FriendRequestRead(BaseModel):
    """
    Response shape for a pending/declined friend request row.

    other_user is whichever side of the request is NOT the current viewer,
    so the same schema works for both the incoming and outgoing lists.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    other_user: UserPublic
    status: str
    created_at: datetime
