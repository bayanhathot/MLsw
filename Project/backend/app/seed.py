"""Idempotent cold seed for clearly labelled demo forum data.

Runs by default as part of every deploy's one-shot `migrate` step (see
docker-compose.yml/docker-compose.prod.yml), right after `alembic upgrade
head`, so the app always launches pre-seeded. Every insert is look-before-
write on a natural key (username/title/comment body/vote), so re-running it
on every redeploy is safe and never creates duplicates. Set
ALLOW_DEMO_SEED=false to opt out entirely; when disabled, main() is a no-op
(prints and returns 0) rather than failing, since it may be chained with
other startup commands.

Manual run::

    python -m app.seed
"""

import os

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database.database import SessionLocal
from app.database.models.forum import ForumComment, ForumPost, ForumPostVote
from app.database.models.user import User

DEMO_USERS = (
    ("demo_aurora", "demo-aurora@cuemix.invalid"),
    ("demo_pulse", "demo-pulse@cuemix.invalid"),
    ("demo_echo", "demo-echo@cuemix.invalid"),
)


def seed_demo_data(db: Session) -> dict[str, int]:
    users: dict[str, User] = {}
    for username, email in DEMO_USERS:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                email=email,
                hashed_password=hash_password(f"demo-only-{username}-password"),
                is_active=True,
            )
            db.add(user)
            db.flush()
        users[username] = user

    examples = (
        (
            "[Demo] Smooth transition tip",
            "[Demo data] Lower the outgoing bass before introducing the next kick.",
            "demo_aurora",
        ),
        (
            "[Demo] Focus mix achievement",
            "[Demo data] I finished a 90-minute focus session without a harsh transition.",
            "demo_pulse",
        ),
    )
    posts: list[ForumPost] = []
    for title, body, username in examples:
        post = db.query(ForumPost).filter(ForumPost.title == title).first()
        if post is None:
            post = ForumPost(author_id=users[username].id, title=title, body=body, is_anonymous=False)
            db.add(post)
            db.flush()
        posts.append(post)

    demo_comment = "[Demo data] This worked nicely in my workout queue too."
    comment = db.query(ForumComment).filter(ForumComment.body == demo_comment).first()
    if comment is None:
        db.add(
            ForumComment(
                post_id=posts[0].id,
                author_id=users["demo_echo"].id,
                body=demo_comment,
                is_anonymous=False,
            )
        )
    vote = db.query(ForumPostVote).filter_by(
        post_id=posts[0].id, user_id=users["demo_pulse"].id
    ).first()
    if vote is None:
        db.add(ForumPostVote(post_id=posts[0].id, user_id=users["demo_pulse"].id, value=1))
    db.commit()
    return {"users": len(users), "posts": len(posts), "comments": 1}


def main() -> None:
    if os.getenv("ALLOW_DEMO_SEED", "true").lower() not in {"1", "true", "yes"}:
        print("Demo seed skipped: ALLOW_DEMO_SEED is explicitly disabled.")
        return
    with SessionLocal() as db:
        result = seed_demo_data(db)
    print(f"Demo seed complete: {result}")


if __name__ == "__main__":
    main()
