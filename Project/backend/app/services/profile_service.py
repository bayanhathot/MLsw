"""Profile updates and engagement dashboard metrics."""

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database.models.forum import ForumComment, ForumCommentVote, ForumPost, ForumPostVote
from app.database.models.profile import Profile


def get_or_create(db: Session, user_id: int) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def engagement_stats(db: Session, user_id: int) -> dict:
    post_votes = (
        db.query(
            func.coalesce(func.sum(case((ForumPostVote.value == 1, 1), else_=0)), 0),
            func.coalesce(func.sum(case((ForumPostVote.value == -1, 1), else_=0)), 0),
        )
        .join(ForumPost, ForumPost.id == ForumPostVote.post_id)
        .filter(ForumPost.author_id == user_id)
        .one()
    )
    comment_votes = (
        db.query(
            func.coalesce(func.sum(case((ForumCommentVote.value == 1, 1), else_=0)), 0),
            func.coalesce(func.sum(case((ForumCommentVote.value == -1, 1), else_=0)), 0),
        )
        .join(ForumComment, ForumComment.id == ForumCommentVote.comment_id)
        .filter(ForumComment.author_id == user_id)
        .one()
    )
    return {
        "received_upvotes": int(post_votes[0] or 0) + int(comment_votes[0] or 0),
        "received_downvotes": int(post_votes[1] or 0) + int(comment_votes[1] or 0),
        "post_count": db.query(ForumPost).filter_by(author_id=user_id).count(),
        "comment_count": db.query(ForumComment).filter_by(author_id=user_id).count(),
    }
