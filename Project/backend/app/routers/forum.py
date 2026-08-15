"""Music-first community posts with a dedicated discussion mode."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.forum import ForumComment, ForumCommentVote, ForumPost, ForumPostVote
from app.database.models.mix import Mix
from app.database.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas import CommentCreate, CommentRead, NotificationRead, PostCreate, PostRead, VoteRequest
from app.services import forum_service, social_service
from app.services.channel_hub import channel_hub

router = APIRouter(prefix="/posts", tags=["community"])


def _visible_or_404(db: Session, post_id: int, viewer_id: int | None) -> ForumPost:
    post = forum_service.post_or_404(db, post_id)
    if not forum_service.can_view_post(db, post, viewer_id):
        raise HTTPException(status_code=404, detail="Post not found.")
    return post


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
async def create_post(
    request: PostCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.kind != "discussion" and request.is_anonymous:
        raise HTTPException(status_code=422, detail="Anonymous posting is available only in Discussions.")
    mix = None
    if request.kind == "mix_share":
        if request.mix_id is None:
            raise HTTPException(status_code=422, detail="Choose a published mix to share.")
        mix = db.query(Mix).filter(Mix.id == request.mix_id, Mix.status == "published").first()
        if mix is None:
            raise HTTPException(status_code=404, detail="Published mix not found.")
    title = (request.title or "").strip()
    if request.kind == "discussion" and not title:
        raise HTTPException(status_code=422, detail="Discussions need a title.")
    if not title:
        title = mix.title if mix is not None else "Music update"

    post = ForumPost(
        author_id=current_user.id,
        title=title,
        body=request.body,
        is_anonymous=request.is_anonymous,
        kind=request.kind,
        visibility=request.visibility,
        mix_id=mix.id if mix else None,
    )
    db.add(post)
    db.flush()
    forum_service.attach_owned(db, request.attachment_ids, current_user.id, "post", post.id)
    db.commit()
    db.refresh(post)
    result = forum_service.build_post(db, post, current_user.id)
    await channel_hub.publish(f"feed:{post.kind}", "post_created", result.model_dump(mode="json"))
    return result


@router.get("/feed", response_model=list[PostRead])
def feed(
    mode: str = Query(default="explore", pattern="^(explore|friends|discussions)$"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ForumPost)
    blocked_ids = social_service.blocked_user_ids(db, current_user.id) if current_user else set()
    if blocked_ids:
        query = query.filter(~ForumPost.author_id.in_(blocked_ids))
    if mode == "discussions":
        query = query.filter(ForumPost.kind == "discussion", ForumPost.visibility == "public")
    elif mode == "friends":
        if current_user is None:
            raise HTTPException(status_code=401, detail="Sign in to see your friends feed.")
        ids = social_service.friend_ids(db, current_user.id) | {current_user.id}
        query = query.filter(
            ForumPost.author_id.in_(ids),
            or_(ForumPost.visibility == "public", ForumPost.visibility == "friends"),
        )
    else:
        query = query.filter(ForumPost.visibility == "public")
    posts = query.order_by(ForumPost.created_at.desc(), ForumPost.id.desc()).offset(offset).limit(limit).all()
    return [forum_service.build_post(db, item, current_user.id if current_user else None) for item in posts]


@router.get("/{post_id}", response_model=PostRead)
def get_post(
    post_id: int,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    post = _visible_or_404(db, post_id, current_user.id if current_user else None)
    return forum_service.build_post(db, post, current_user.id if current_user else None)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = forum_service.post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this post.")
    kind = post.kind  # capture before delete -- the object is gone after db.commit()
    media_paths = forum_service.attachment_paths(db, "post", post.id)
    for comment in db.query(ForumComment).filter_by(post_id=post.id).all():
        media_paths.extend(forum_service.attachment_paths(db, "comment", comment.id))
    db.delete(post)
    db.commit()
    forum_service.delete_files(media_paths)
    await channel_hub.publish(f"feed:{kind}", "post_deleted", {"post_id": post_id})
    await channel_hub.publish(f"post:{post_id}", "post_deleted", {"post_id": post_id})


async def _vote_post(post_id: int, value: int | None, user: User, db: Session):
    post = _visible_or_404(db, post_id, user.id)
    changed = forum_service.set_vote(db, ForumPostVote, "post_id", post.id, user.id, value)
    notification = None
    if value is not None and changed:
        notification = forum_service.notify(db, post.author_id, user.id, "post_vote", f"{user.username} reacted to your post.", "post", post.id)
    db.commit()
    result = forum_service.build_post(db, post, user.id)
    if notification:
        notification_payload = NotificationRead.model_validate(notification).model_dump(mode="json")
        await channel_hub.publish(f"user:{post.author_id}", "notification", notification_payload)
    await channel_hub.publish(f"post:{post.id}", "vote_changed", {"score": result.score})
    return result


@router.post("/{post_id}/vote", response_model=PostRead)
async def vote_post(post_id: int, request: VoteRequest, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_post(post_id, request.value, current_user, db)


@router.delete("/{post_id}/vote", response_model=PostRead)
async def remove_post_vote(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_post(post_id, None, current_user, db)


@router.post("/{post_id}/like", response_model=PostRead, include_in_schema=False)
async def like_post_compat(post_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    _visible_or_404(db, post_id, current_user.id if current_user else None)
    query = db.query(ForumComment).filter_by(post_id=post_id)
    if current_user is not None:
        blocked_ids = social_service.blocked_user_ids(db, current_user.id)
        if blocked_ids:
            query = query.filter(~ForumComment.author_id.in_(blocked_ids))
    comments = query.order_by(ForumComment.created_at.asc()).offset(offset).limit(limit).all()
    return [forum_service.build_comment(db, item, current_user.id if current_user else None) for item in comments]


@router.post("/{post_id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: int,
    request: CommentCreate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = _visible_or_404(db, post_id, current_user.id)
    if post.kind != "discussion" and request.is_anonymous:
        raise HTTPException(status_code=422, detail="Anonymous comments are available only in Discussions.")
    comment = ForumComment(post_id=post.id, author_id=current_user.id, body=request.body, is_anonymous=request.is_anonymous)
    db.add(comment)
    db.flush()
    forum_service.attach_owned(db, request.attachment_ids, current_user.id, "comment", comment.id)
    actor_label = "Someone" if request.is_anonymous else current_user.username
    notification = forum_service.notify(db, post.author_id, current_user.id, "comment", f"{actor_label} commented on your post.", "post", post.id)
    db.commit()
    db.refresh(comment)
    result = forum_service.build_comment(db, comment, current_user.id)
    if notification:
        notification_payload = NotificationRead.model_validate(notification).model_dump(mode="json")
        await channel_hub.publish(f"user:{post.author_id}", "notification", notification_payload)
    await channel_hub.publish(f"post:{post.id}", "comment_created", result.model_dump(mode="json"))
    return result


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(post_id: int, comment_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    comment = forum_service.comment_or_404(db, comment_id)
    if comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment.")
    media_paths = forum_service.attachment_paths(db, "comment", comment.id)
    db.delete(comment)
    db.commit()
    forum_service.delete_files(media_paths)
    await channel_hub.publish(f"post:{post_id}", "comment_deleted", {"comment_id": comment_id})


def _visible_comment_or_404(db: Session, comment_id: int, viewer_id: int) -> ForumComment:
    comment = forum_service.comment_or_404(db, comment_id)
    _visible_or_404(db, comment.post_id, viewer_id)
    if social_service.is_blocked_between(db, viewer_id, comment.author_id):
        raise HTTPException(status_code=404, detail="Comment not found.")
    return comment


async def _vote_comment(comment_id: int, value: int | None, user: User, db: Session):
    comment = _visible_comment_or_404(db, comment_id, user.id)
    changed = forum_service.set_vote(db, ForumCommentVote, "comment_id", comment.id, user.id, value)
    notification = None
    if value is not None and changed:
        notification = forum_service.notify(db, comment.author_id, user.id, "comment_vote", f"{user.username} reacted to your comment.", "comment", comment.id)
    db.commit()
    result = forum_service.build_comment(db, comment, user.id)
    if notification:
        notification_payload = NotificationRead.model_validate(notification).model_dump(mode="json")
        await channel_hub.publish(f"user:{comment.author_id}", "notification", notification_payload)
    await channel_hub.publish(
        f"post:{comment.post_id}", "comment_vote_changed", {"comment_id": comment.id, "score": result.score}
    )
    return result


@router.post("/comments/{comment_id}/vote", response_model=CommentRead)
async def vote_comment(comment_id: int, request: VoteRequest, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_comment(comment_id, request.value, current_user, db)


@router.delete("/comments/{comment_id}/vote", response_model=CommentRead)
async def remove_comment_vote(comment_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _vote_comment(comment_id, None, current_user, db)
