"""
schemas package

Pydantic schemas define the shape of request and response data.

This package splits schemas by domain, mirroring how routers/ and
services/ are already split. Re-exporting everything here means
existing code (e.g. `from app.schemas import UserCreate`) keeps working
without changes.
"""

from app.schemas.auth import Token, UserCreate, UserLogin, UserRead
from app.schemas.friends import FriendRequestCreate, FriendRequestRead
from app.schemas.mixes import MixRead, MixSegmentRead
from app.schemas.play_events import PlayEventCreate, PlayEventRead
from app.schemas.posts import CommentCreate, CommentRead, PostCreate, PostRead, ShareRead
from app.schemas.profiles import FavoriteArtist, ProfileRead, ProfileStatsRead, ProfileUpdate
from app.schemas.users import FriendStatus, UserProfilePage, UserPublic

__all__ = [
    "Token",
    "UserCreate",
    "UserLogin",
    "UserRead",
    "FriendRequestCreate",
    "FriendRequestRead",
    "FriendStatus",
    "UserProfilePage",
    "UserPublic",
    "MixRead",
    "MixSegmentRead",
    "PostCreate",
    "PostRead",
    "CommentCreate",
    "CommentRead",
    "ShareRead",
    "ProfileRead",
    "ProfileUpdate",
    "FavoriteArtist",
    "ProfileStatsRead",
    "PlayEventCreate",
    "PlayEventRead",
]
