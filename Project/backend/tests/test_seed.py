from conftest import TestingSessionLocal

from app.database.models.forum import ForumComment, ForumPost
from app.database.models.user import User
from app.seed import main, seed_demo_data


def test_demo_seed_is_labelled_and_idempotent(db_session):
    first = seed_demo_data(db_session)
    second = seed_demo_data(db_session)
    assert first == second == {"users": 3, "posts": 2, "comments": 1}
    assert db_session.query(User).count() == 3
    assert db_session.query(ForumPost).count() == 2
    assert db_session.query(ForumComment).count() == 1
    assert all(post.title.startswith("[Demo]") for post in db_session.query(ForumPost).all())


def test_main_seeds_by_default_when_allow_demo_seed_is_unset(monkeypatch, db_session):
    """This is what makes the app launch pre-seeded: main() (invoked as
    `python -m app.seed` from the migrate service, see docker-compose.yml)
    must seed with no explicit ALLOW_DEMO_SEED, not just when it's set."""

    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
    monkeypatch.setattr("app.seed.SessionLocal", TestingSessionLocal)

    main()

    assert db_session.query(User).filter(User.username == "demo_aurora").first() is not None


def test_main_is_a_graceful_no_op_when_allow_demo_seed_is_false(monkeypatch, db_session):
    """The deploy chain runs this chained with `&&` after alembic (see
    docker-compose.yml's migrate command) -- it must exit cleanly, not raise,
    or a deploy with seeding explicitly disabled would fail outright."""

    monkeypatch.setenv("ALLOW_DEMO_SEED", "false")
    monkeypatch.setattr("app.seed.SessionLocal", TestingSessionLocal)

    main()  # must not raise

    assert db_session.query(User).filter(User.username == "demo_aurora").first() is None
