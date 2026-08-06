"""
users.py

Pydantic schemas for public user lookup (search + profile viewing).

These describe OTHER users as seen by the current logged-in user,
as opposed to auth.py's UserRead, which describes yourself.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Friendship status of the viewed user, relative to the current logged-in viewer.
#
# "self"              -> you are viewing your own profile
# "none"              -> no relationship exists
# "pending_outgoing"  -> you sent a friend request that is still pending
# "pending_incoming"  -> they sent you a friend request that is still pending
# "friends"           -> an accepted friendship exists
FriendStatus = Literal["self", "none", "pending_outgoing", "pending_incoming", "friends"]


class UserPublic(BaseModel):
    """
    Minimal public info about another user.

    Used in search results and friend request lists.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    friend_status: FriendStatus


class UserProfilePage(BaseModel):
    """
    Response shape for GET /users/{username}.

    display_name/avatar_url/bio/favorite_genres come from the user's
    Profile row (Phase 3) if they've set one; null otherwise, since a
    profile is only created on the owner's first edit, not from being
    viewed.
    """

    id: int
    username: str
    created_at: datetime
    friend_status: FriendStatus
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    favorite_genres: list[str] | None = None
