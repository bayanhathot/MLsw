from app.database.models.forum import ForumComment, ForumPost
from app.database.models.user import User
from app.seed import seed_demo_data


def test_demo_seed_is_labelled_and_idempotent(db_session):
    first = seed_demo_data(db_session)
    second = seed_demo_data(db_session)
    assert first == second == {"users": 3, "posts": 2, "comments": 1}
    assert db_session.query(User).count() == 3
    assert db_session.query(ForumPost).count() == 2
    assert db_session.query(ForumComment).count() == 1
    assert all(post.title.startswith("[Demo]") for post in db_session.query(ForumPost).all())
