"""Public forum with anonymous posting, comments, and up/down votes."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.forum import ForumComment, ForumCommentVote, ForumPost, ForumPostVote
from app.database.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas import CommentCreate, CommentRead, NotificationRead, PostCreate, PostRead, VoteRequest
from app.services import forum_service
from app.services.notification_service import notification_hub

router = APIRouter(prefix="/posts", tags=["forum"])


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    request: PostCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = ForumPost(
        author_id=current_user.id,
        title=request.title,
        body=request.body,
        is_anonymous=request.is_anonymous,
    )
    db.add(post)
    db.flush()
    forum_service.attach_owned(db, request.attachment_ids, current_user.id, "post", post.id)
    db.commit()
    db.refresh(post)
    return forum_service.build_post(db, post, current_user.id)


@router.get("/feed", response_model=list[PostRead])
def feed(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    posts = db.query(ForumPost).order_by(ForumPost.created_at.desc(), ForumPost.id.desc()).offset(offset).limit(limit).all()
    return [forum_service.build_post(db, item, current_user.id if current_user else None) for item in posts]


@router.get("/{post_id}", response_model=PostRead)
def get_post(
    post_id: int,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    return forum_service.build_post(db, forum_service.post_or_404(db, post_id), current_user.id if current_user else None)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = forum_service.post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this post.")
    media_paths = forum_service.attachment_paths(db, "post", post.id)
    for comment in db.query(ForumComment).filter_by(post_id=post.id).all():
        media_paths.extend(forum_service.attachment_paths(db, "comment", comment.id))
    db.delete(post)
    db.commit()
    forum_service.delete_files(media_paths)


async def _vote_post(post_id: int, value: int | None, user: User, db: Session):
    post = forum_service.post_or_404(db, post_id)
    changed = forum_service.set_vote(db, ForumPostVote, "post_id", post.id, user.id, value)
    notification = None
    if value is not None and changed:
        notification = forum_service.notify(db, post.author_id, user.id, "post_vote", f"{user.username} voted on your post.", "post", post.id)
    db.commit()
    if notification:
        await notification_hub.publish(
            post.author_id, NotificationRead.model_validate(notification).model_dump(mode="json")
        )
    return forum_service.build_post(db, post, user.id)


@router.post("/{post_id}/vote", response_model=PostRead)
async def vote_post(post_id: int, request: VoteRequest, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_post(post_id, request.value, current_user, db)


@router.delete("/{post_id}/vote", response_model=PostRead)
async def remove_post_vote(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_post(post_id, None, current_user, db)


@router.post("/{post_id}/like", response_model=PostRead, include_in_schema=False)
async def like_post_compat(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Compatibility alias: a legacy like is an upvote."""

    return await _vote_post(post_id, 1, current_user, db)


@router.delete("/{post_id}/like", response_model=PostRead, include_in_schema=False)
async def unlike_post_compat(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_post(post_id, None, current_user, db)


@router.get("/{post_id}/comments", response_model=list[CommentRead])
def list_comments(
    post_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    forum_service.post_or_404(db, post_id)
    comments = db.query(ForumComment).filter_by(post_id=post_id).order_by(ForumComment.created_at.asc()).offset(offset).limit(limit).all()
    return [forum_service.build_comment(db, item, current_user.id if current_user else None) for item in comments]


@router.post("/{post_id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: int,
    request: CommentCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = forum_service.post_or_404(db, post_id)
    comment = ForumComment(post_id=post.id, author_id=current_user.id, body=request.body, is_anonymous=request.is_anonymous)
    db.add(comment)
    db.flush()
    forum_service.attach_owned(db, request.attachment_ids, current_user.id, "comment", comment.id)
    actor_label = "Someone" if request.is_anonymous else current_user.username
    notification = forum_service.notify(
        db,
        post.author_id,
        current_user.id,
        "comment",
        f"{actor_label} commented on your post.",
        "post",
        post.id,
    )
    db.commit()
    db.refresh(comment)
    if notification:
        await notification_hub.publish(
            post.author_id, NotificationRead.model_validate(notification).model_dump(mode="json")
        )
    return forum_service.build_comment(db, comment, current_user.id)


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(post_id: int, comment_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    comment = forum_service.comment_or_404(db, comment_id)
    if comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment.")
    media_paths = forum_service.attachment_paths(db, "comment", comment.id)
    db.delete(comment)
    db.commit()
    forum_service.delete_files(media_paths)


async def _vote_comment(comment_id: int, value: int | None, user: User, db: Session):
    comment = forum_service.comment_or_404(db, comment_id)
    changed = forum_service.set_vote(db, ForumCommentVote, "comment_id", comment.id, user.id, value)
    notification = None
    if value is not None and changed:
        notification = forum_service.notify(db, comment.author_id, user.id, "comment_vote", f"{user.username} voted on your comment.", "comment", comment.id)
    db.commit()
    if notification:
        await notification_hub.publish(
            comment.author_id, NotificationRead.model_validate(notification).model_dump(mode="json")
        )
    return forum_service.build_comment(db, comment, user.id)


@router.post("/comments/{comment_id}/vote", response_model=CommentRead)
async def vote_comment(comment_id: int, request: VoteRequest, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_comment(comment_id, request.value, current_user, db)


@router.delete("/comments/{comment_id}/vote", response_model=CommentRead)
async def remove_comment_vote(comment_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_comment(comment_id, None, current_user, db)
