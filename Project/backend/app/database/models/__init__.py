"""
models package

This package imports all SQLAlchemy models.

Alembic imports this package so all models are registered in Base.metadata.
"""

from app.database.models.friendship import Friendship
from app.database.models.mix import Mix, MixSegment
from app.database.models.play_event import PlayEvent
from app.database.models.post import Post
from app.database.models.post_comment import PostComment
from app.database.models.post_like import PostLike
from app.database.models.post_share import PostShare
from app.database.models.profile import Profile
from app.database.models.user import User

__all__ = [
    "User",
    "Friendship",
    "Mix",
    "MixSegment",
    "Post",
    "PostLike",
    "PostComment",
    "PostShare",
    "Profile",
    "PlayEvent",
]