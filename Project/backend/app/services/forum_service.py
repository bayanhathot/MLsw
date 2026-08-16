"""Forum persistence, response shaping, and attachment ownership rules."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models.attachment import Attachment
from app.database.models.forum import ForumComment, ForumCommentVote, ForumPost, ForumPostVote
from app.database.models.messaging import Notification
from app.database.models.mix import Mix
from app.database.models.user import User
from app.schemas import AttachmentRead, CommentRead, PostRead
from app.services import social_service


def can_view_post(db: Session, post: ForumPost, viewer_id: int | None) -> bool:
    """Shared post-visibility rule used by the forum router and attachment serving."""

    if viewer_id is not None and post.author_id is not None and social_service.is_blocked_between(db, viewer_id, post.author_id):
        return False
    if post.visibility == "public":
        return True
    if viewer_id is None:
        return False
    return viewer_id == post.author_id or social_service.are_friends(db, viewer_id, post.author_id)


def attachment_paths(db: Session, field: str, entity_id: int) -> list:
    """Resolve controlled media paths before their rows are cascade-deleted."""

    # Imported lazily so tests can replace UPLOAD_DIR without import cycles.
    from app.services.upload_queue import UPLOAD_DIR

    column = getattr(Attachment, f"{field}_id")
    root = UPLOAD_DIR.resolve()
    paths = []
    for attachment in db.query(Attachment).filter(column == entity_id).all():
        path = (root / attachment.storage_name).resolve()
        if path.parent == root:
            paths.append(path)
    return paths


def delete_files(paths: list) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # The database delete remains correct; the opt-in orphan cleanup
            # command can retry filesystem cleanup later.
            pass


def post_or_404(db: Session, post_id: int) -> ForumPost:
    post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found.")
    return post


def comment_or_404(db: Session, comment_id: int) -> ForumComment:
    comment = db.query(ForumComment).filter(ForumComment.id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found.")
    return comment


def attach_owned(
    db: Session, attachment_ids: list[int], owner_id: int, entity: str, entity_id: int
) -> None:
    if not attachment_ids:
        return
    if len(set(attachment_ids)) != len(attachment_ids):
        raise HTTPException(status_code=422, detail="Attachment IDs must be unique.")
    attachments = db.query(Attachment).filter(Attachment.id.in_(attachment_ids)).all()
    if len(attachments) != len(attachment_ids):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    for attachment in attachments:
        if attachment.owner_id != owner_id:
            raise HTTPException(status_code=403, detail="You do not own this attachment.")
        if any((attachment.post_id, attachment.comment_id, attachment.message_id)):
            raise HTTPException(status_code=409, detail="Attachment is already in use.")
        setattr(attachment, f"{entity}_id", entity_id)


def _attachments(db: Session, field: str, entity_id: int) -> list[AttachmentRead]:
    column = getattr(Attachment, f"{field}_id")
    return [AttachmentRead.model_validate(row) for row in db.query(Attachment).filter(column == entity_id).all()]


def _score(db: Session, model, foreign_key: str, entity_id: int) -> int:
    column = getattr(model, foreign_key)
    return int(db.query(func.coalesce(func.sum(model.value), 0)).filter(column == entity_id).scalar() or 0)


def build_post(db: Session, post: ForumPost, viewer_id: int | None) -> PostRead:
    author = db.query(User).filter(User.id == post.author_id).first()
    my_vote = 0
    if viewer_id is not None:
        vote = db.query(ForumPostVote).filter_by(post_id=post.id, user_id=viewer_id).first()
        my_vote = vote.value if vote else 0
    shared_mix = None
    if post.mix_id is not None:
        mix = db.query(Mix).filter(Mix.id == post.mix_id, Mix.status == "published").first()
        if mix is not None:
            owner = db.query(User).filter(User.id == mix.owner_id).first()
            shared_mix = {
                "id": mix.id,
                "title": mix.title,
                "prompt": mix.prompt,
                "cover_url": mix.cover_url,
                "owner_username": owner.username if owner else "Deleted user",
                "segment_count": len(mix.segments),
            }
    return PostRead(
        id=post.id,
        author_id=None if post.is_anonymous else post.author_id,
        author_username="Anonymous" if post.is_anonymous else (author.username if author else "Deleted user"),
        title=post.title,
        body=post.body,
        is_anonymous=post.is_anonymous,
        kind=post.kind,
        visibility=post.visibility,
        mix=shared_mix,
        can_delete=viewer_id == post.author_id,
        score=_score(db, ForumPostVote, "post_id", post.id),
        comment_count=db.query(ForumComment).filter(ForumComment.post_id == post.id).count(),
        my_vote=my_vote,
        attachments=_attachments(db, "post", post.id),
        created_at=post.created_at,
    )


def build_comment(db: Session, comment: ForumComment, viewer_id: int | None) -> CommentRead:
    author = db.query(User).filter(User.id == comment.author_id).first()
    my_vote = 0
    if viewer_id is not None:
        vote = db.query(ForumCommentVote).filter_by(comment_id=comment.id, user_id=viewer_id).first()
        my_vote = vote.value if vote else 0
    return CommentRead(
        id=comment.id,
        author_id=None if comment.is_anonymous else comment.author_id,
        author_username="Anonymous" if comment.is_anonymous else (author.username if author else "Deleted user"),
        body=comment.body,
        is_anonymous=comment.is_anonymous,
        can_delete=viewer_id == comment.author_id,
        score=_score(db, ForumCommentVote, "comment_id", comment.id),
        my_vote=my_vote,
        attachments=_attachments(db, "comment", comment.id),
        created_at=comment.created_at,
        parent_comment_id=comment.parent_comment_id,
    )


def notify(
    db: Session,
    recipient_id: int,
    actor_id: int,
    kind: str,
    message: str,
    entity_type: str,
    entity_id: int,
) -> Notification | None:
    if recipient_id == actor_id:
        return None
    notification = Notification(
        recipient_id=recipient_id,
        actor_id=actor_id,
        kind=kind,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(notification)
    return notification


def set_vote(db: Session, model, key: str, entity_id: int, user_id: int, value: int | None) -> bool:
    vote = db.query(model).filter_by(**{key: entity_id, "user_id": user_id}).first()
    if value is None:
        if vote:
            db.delete(vote)
            return True
    elif vote:
        if vote.value == value:
            return False
        vote.value = value
        return True
    else:
        db.add(model(**{key: entity_id, "user_id": user_id, "value": value}))
        return True
    return False
