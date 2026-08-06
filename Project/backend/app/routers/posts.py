"""
posts.py

Routes for posts (feed entries): creating them, the feed itself,
likes, comments, and shares.

A post IS a mix - POST /posts generates the mix content from a prompt
and shares it in one call (see services/post_service.py::create_post).
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models.post import Post
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import CommentCreate, CommentRead, MixRead, PostCreate, PostRead, ShareRead
from app.services import post_service

router = APIRouter(prefix="/posts", tags=["posts"])


def build_post_read(db: Session, post: Post, viewer_id: int) -> PostRead:
    return PostRead(
        id=post.id,
        author_id=post.author_id,
        author_username=post.author.username,
        description=post.description,
        mix=MixRead.model_validate(post.mix),
        like_count=post_service.get_like_count(db, post.id),
        comment_count=post_service.get_comment_count(db, post.id),
        share_count=post_service.get_share_count(db, post.id),
        liked_by_me=post_service.is_liked_by(db, post.id, viewer_id),
        created_at=post.created_at,
    )


def build_comment_read(comment) -> CommentRead:
    return CommentRead(
        id=comment.id,
        author_id=comment.author_id,
        author_username=comment.author.username,
        body=comment.body,
        created_at=comment.created_at,
    )


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    post_data: PostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = post_service.create_post(
        db=db,
        author_id=current_user.id,
        prompt=post_data.prompt,
        description=post_data.description,
    )

    return build_post_read(db, post, current_user.id)


@router.get("/feed", response_model=list[PostRead])
def get_feed(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    posts = post_service.get_feed(db, current_user.id, limit=limit, offset=offset)

    return [build_post_read(db, post, current_user.id) for post in posts]


@router.get("/{post_id}", response_model=PostRead)
def get_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = post_service.get_post(db, post_id)

    return build_post_read(db, post, current_user.id)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post_service.delete_post(db, post_id, current_user.id)


@router.post("/{post_id}/like", response_model=PostRead)
def like_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post_service.like_post(db, post_id, current_user.id)
    post = post_service.get_post(db, post_id)

    return build_post_read(db, post, current_user.id)


@router.delete("/{post_id}/like", response_model=PostRead)
def unlike_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post_service.unlike_post(db, post_id, current_user.id)
    post = post_service.get_post(db, post_id)

    return build_post_read(db, post, current_user.id)


@router.get("/{post_id}/comments", response_model=list[CommentRead])
def get_comments(
    post_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comments = post_service.list_comments(db, post_id, limit=limit, offset=offset)

    return [build_comment_read(comment) for comment in comments]


@router.post("/{post_id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
def create_comment(
    post_id: int,
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = post_service.add_comment(db, post_id, current_user.id, comment_data.body)

    return build_comment_read(comment)


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    post_id: int,
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post_service.delete_comment(db, post_id, comment_id, current_user.id)


@router.post("/{post_id}/share", response_model=ShareRead)
def share_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    share_count = post_service.record_share(db, post_id, current_user.id)

    return ShareRead(share_count=share_count)
