"""Profile updates and viewer-safe engagement dashboard metrics."""

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.database.models.forum import (
    ForumComment,
    ForumPost,
    ForumPostVote,
)
from app.database.models.profile import Profile
from app.services import social_service


def get_or_create(db: Session, user_id: int) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _visible_post_condition(db: Session, viewer_id: int | None):
    conditions = [ForumPost.visibility == "public"]
    blocked_ids: set[int] = set()
    if viewer_id is not None:
        visible_friend_ids = social_service.friend_ids(db, viewer_id) | {viewer_id}
        conditions.append(
            and_(
                ForumPost.visibility == "friends",
                ForumPost.author_id.in_(visible_friend_ids),
            )
        )
        blocked_ids = social_service.blocked_user_ids(db, viewer_id)
    condition = or_(*conditions)
    if blocked_ids:
        condition = and_(condition, ~ForumPost.author_id.in_(blocked_ids))
    return condition


def engagement_stats(
    db: Session, user_id: int, viewer_id: int | None = None
) -> dict:
    """Return activity the viewer may safely associate with this profile.

    Owners see their complete totals. Everyone else only sees non-anonymous
    activity on posts they are allowed to view. This prevents public profile
    counters from revealing friends-only activity or linking anonymous posts
    back to their author. Comment totals count replies from other users on the
    profile owner's posts. Received vote totals cover authored posts only.
    """

    owner_view = viewer_id == user_id
    visible_post = _visible_post_condition(db, viewer_id)

    posts = db.query(ForumPost).filter(ForumPost.author_id == user_id)
    comments_received = (
        db.query(ForumComment)
        .join(ForumPost, ForumPost.id == ForumComment.post_id)
        .filter(
            ForumPost.author_id == user_id,
            ForumComment.author_id != user_id,
        )
    )
    post_vote_query = (
        db.query(
            func.coalesce(func.sum(case((ForumPostVote.value == 1, 1), else_=0)), 0),
            func.coalesce(func.sum(case((ForumPostVote.value == -1, 1), else_=0)), 0),
        )
        .join(ForumPost, ForumPost.id == ForumPostVote.post_id)
        .filter(ForumPost.author_id == user_id)
    )
    if not owner_view:
        posts = posts.filter(ForumPost.is_anonymous.is_(False), visible_post)
        comments_received = comments_received.filter(
            ForumPost.is_anonymous.is_(False), visible_post
        )
        post_vote_query = post_vote_query.filter(
            ForumPost.is_anonymous.is_(False), visible_post
        )

    post_votes = post_vote_query.one()
    return {
        "received_upvotes": int(post_votes[0] or 0),
        "received_downvotes": int(post_votes[1] or 0),
        "post_count": posts.count(),
        "comment_count": comments_received.count(),
    }
