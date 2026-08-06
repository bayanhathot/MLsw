"""
post_service.py

Business logic for posts (feed entries), likes, comments, and shares.

The router handles HTTP and shapes ORM objects into response schemas;
this file only deals with persistence and the rules around it.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models.mix import Mix
from app.database.models.post import Post
from app.database.models.post_comment import PostComment
from app.database.models.post_like import PostLike
from app.database.models.post_share import PostShare
from app.services import mix_service
from app.services.friend_service import get_friend_ids


def create_post(db: Session, author_id: int, prompt: str, description: str) -> Post:
    """
    Generate a mix from the prompt and share it as a new post, in one step.
    """

    mix = mix_service.create_mix(db, creator_id=author_id, prompt=prompt)

    post = Post(author_id=author_id, mix_id=mix.id, description=description)
    db.add(post)
    db.commit()
    db.refresh(post)

    return post


def get_post(db: Session, post_id: int) -> Post:
    post = db.query(Post).filter(Post.id == post_id).first()

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found.",
        )

    return post


def get_feed(db: Session, viewer_id: int, limit: int = 20, offset: int = 0) -> list[Post]:
    """
    Posts authored by the viewer or one of their accepted friends,
    newest first.
    """

    author_ids = get_friend_ids(db, viewer_id) + [viewer_id]

    return (
        db.query(Post)
        .filter(Post.author_id.in_(author_ids))
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_user_posts(db: Session, user_id: int, limit: int = 20, offset: int = 0) -> list[Post]:
    return (
        db.query(Post)
        .filter(Post.author_id == user_id)
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def delete_post(db: Session, post_id: int, current_user_id: int) -> None:
    post = get_post(db, post_id)

    if post.author_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can delete this post.",
        )

    mix = db.query(Mix).filter(Mix.id == post.mix_id).first()

    db.delete(post)

    if mix is not None:
        db.delete(mix)

    db.commit()


def like_post(db: Session, post_id: int, user_id: int) -> None:
    get_post(db, post_id)

    existing = db.query(PostLike).filter_by(post_id=post_id, user_id=user_id).first()

    if existing is not None:
        return

    db.add(PostLike(post_id=post_id, user_id=user_id))
    db.commit()


def unlike_post(db: Session, post_id: int, user_id: int) -> None:
    get_post(db, post_id)

    like = db.query(PostLike).filter_by(post_id=post_id, user_id=user_id).first()

    if like is not None:
        db.delete(like)
        db.commit()


def add_comment(db: Session, post_id: int, author_id: int, body: str) -> PostComment:
    get_post(db, post_id)

    comment = PostComment(post_id=post_id, author_id=author_id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return comment


def list_comments(db: Session, post_id: int, limit: int = 50, offset: int = 0) -> list[PostComment]:
    get_post(db, post_id)

    return (
        db.query(PostComment)
        .filter(PostComment.post_id == post_id)
        .order_by(PostComment.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def delete_comment(db: Session, post_id: int, comment_id: int, current_user_id: int) -> None:
    comment = (
        db.query(PostComment)
        .filter(PostComment.id == comment_id, PostComment.post_id == post_id)
        .first()
    )

    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found.",
        )

    if comment.author_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the comment author can delete it.",
        )

    db.delete(comment)
    db.commit()


def record_share(db: Session, post_id: int, user_id: int) -> int:
    """
    Record that user_id shared post_id, at most once per user, and
    return the updated share count.
    """

    get_post(db, post_id)

    existing = db.query(PostShare).filter_by(post_id=post_id, user_id=user_id).first()

    if existing is None:
        db.add(PostShare(post_id=post_id, user_id=user_id))
        db.commit()

    return get_share_count(db, post_id)


def get_like_count(db: Session, post_id: int) -> int:
    return db.query(PostLike).filter(PostLike.post_id == post_id).count()


def get_comment_count(db: Session, post_id: int) -> int:
    return db.query(PostComment).filter(PostComment.post_id == post_id).count()


def get_share_count(db: Session, post_id: int) -> int:
    return db.query(PostShare).filter(PostShare.post_id == post_id).count()


def is_liked_by(db: Session, post_id: int, user_id: int) -> bool:
    return db.query(PostLike).filter_by(post_id=post_id, user_id=user_id).first() is not None
