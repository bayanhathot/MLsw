"""
posts.py

Pydantic schemas for posts (feed entries), comments, and share counts.

A post IS a mix - there is no separate text-post type. Creating a post
generates its mix content from a prompt in the same call (see
services/post_service.py::create_post).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.mixes import MixRead


class PostCreate(BaseModel):
    """
    Request body for POST /posts.
    """

    prompt: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=500)


class PostRead(BaseModel):
    """
    A feed entry: the mix, its description, and social counts relative
    to the current viewer.

    like_count/comment_count/share_count/liked_by_me are computed by
    post_service, not direct ORM attributes, so this is always built
    manually rather than via Model.model_validate(post).
    """

    id: int
    author_id: int
    author_username: str
    description: str
    mix: MixRead
    like_count: int
    comment_count: int
    share_count: int
    liked_by_me: bool
    created_at: datetime


class CommentCreate(BaseModel):
    """
    Request body for POST /posts/{post_id}/comments.
    """

    body: str = Field(min_length=1, max_length=1000)


class CommentRead(BaseModel):
    """
    Response shape for one comment.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    author_username: str
    body: str
    created_at: datetime


class ShareRead(BaseModel):
    """
    Response shape for POST /posts/{post_id}/share.
    """

    share_count: int
