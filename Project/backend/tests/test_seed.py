"""Coverage for the cold-seed dataset generator (app/coldseed/build.py) and
its app/seed.py entry point."""

from conftest import TestingSessionLocal

from app.coldseed import config
from app.coldseed.build import TARGET_USER_COUNT, run_cold_seed
from app.database.models.forum import ForumComment, ForumPost, ForumPostVote
from app.database.models.messaging import DirectMessage, Notification
from app.database.models.mix import Mix, MixSegment
from app.database.models.music_identity import ListeningEvent, UserMusicProfile
from app.database.models.profile import Profile
from app.database.models.seed_state import ColdSeedRun
from app.database.models.session import DJSession
from app.database.models.social import Friendship
from app.database.models.user import User
from app.services import music_identity_service
from app.seed import main, seed_demo_data

TEST_VERSION = "test-v1"
TEST_SEED = 4242


def _run(db_session):
    return run_cold_seed(db_session, version=TEST_VERSION, random_seed=TEST_SEED)


def test_cold_seed_creates_roughly_fifty_users_with_both_public_and_private_profiles(db_session):
    result = _run(db_session)
    assert result["users"] == TARGET_USER_COUNT
    assert db_session.query(User).count() == TARGET_USER_COUNT

    public_count = db_session.query(UserMusicProfile).filter_by(visibility="public").count()
    friends_count = db_session.query(UserMusicProfile).filter_by(visibility="friends").count()
    private_count = db_session.query(UserMusicProfile).filter_by(visibility="private").count()
    assert public_count + friends_count + private_count == TARGET_USER_COUNT
    # ~70% public (a "friends" sliver counts toward the public-ish cohort),
    # ~30% private -- loose bounds since the exact split has some randomness
    # within the public cohort (a few land on "friends" instead of "public").
    assert public_count > 0
    assert private_count > 0
    assert 12 <= private_count <= 18  # target is round(50 * 0.3) == 15

    # Every user has a real profile with a display name, not a placeholder.
    profiles = db_session.query(Profile).all()
    assert len(profiles) == TARGET_USER_COUNT
    for profile in profiles:
        assert profile.display_name and " " in profile.display_name
    usernames = [row.username for row in db_session.query(User).all()]
    assert len(set(usernames)) == TARGET_USER_COUNT
    assert not any(name.lower().startswith("user") and name[4:].isdigit() for name in usernames)


def test_a_seeded_account_can_actually_log_in_through_the_real_endpoint(client, db_session):
    # A pure-ORM check of the stored email wouldn't catch this: pydantic's
    # EmailStr (used by both /auth/register and /auth/login) rejects some
    # RFC 2606 "obviously fake" TLDs outright as special-use domains (see
    # build.py's own comment on this) -- only a real request against
    # /auth/login proves a seeded account is actually usable, not just
    # present in the database.
    _run(db_session)
    user = db_session.query(User).first()
    password = f"coldseed-{TEST_VERSION}-{user.username}"

    response = client.post("/auth/login", json={"email": user.email, "password": password})

    assert response.status_code == 200, response.text
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == user.username


def test_cold_seed_creates_around_five_hundred_posts_with_valid_engagement(db_session):
    _run(db_session)

    post_count = db_session.query(ForumPost).count()
    assert 300 <= post_count <= 700  # ~10/user average, some natural spread

    comment_count = db_session.query(ForumComment).count()
    assert comment_count > post_count  # "much more" event/engagement data than posts

    vote_count = db_session.query(ForumPostVote).count()
    assert vote_count > post_count

    # No lorem-ipsum/placeholder content, and no comment predates its post.
    posts = db_session.query(ForumPost).all()
    assert not any("lorem" in post.body.lower() for post in posts)
    assert not any(post.title.strip() == "Test Post" for post in posts)

    users_by_id = {user.id: user for user in db_session.query(User).all()}
    for post in posts:
        assert post.created_at >= users_by_id[post.author_id].created_at
    for comment in db_session.query(ForumComment).all():
        post = db_session.get(ForumPost, comment.post_id)
        assert comment.created_at >= post.created_at
        assert comment.created_at >= users_by_id[comment.author_id].created_at


def test_cold_seed_creates_logically_valid_nested_replies(db_session):
    _run(db_session)

    comments = db_session.query(ForumComment).all()
    replies = [comment for comment in comments if comment.parent_comment_id is not None]
    assert len(replies) > 0  # the whole point of this test

    comments_by_id = {comment.id: comment for comment in comments}
    for reply in replies:
        parent = comments_by_id[reply.parent_comment_id]
        assert parent.post_id == reply.post_id  # same-post rule the endpoint also enforces
        assert parent.parent_comment_id is None  # single-level only, no reply-to-a-reply
        assert reply.created_at >= parent.created_at
        assert reply.author_id != parent.author_id  # nobody replies to themselves

    notification_kinds = {row.kind for row in db_session.query(Notification).all()}
    assert "comment_reply" in notification_kinds


def test_cold_seed_creates_a_valid_social_graph(db_session):
    _run(db_session)

    friendships = db_session.query(Friendship).all()
    assert len(friendships) >= 50
    for row in friendships:
        assert row.user_a_id < row.user_b_id  # the model's own ordering constraint

    dm_count = db_session.query(DirectMessage).count()
    assert dm_count > 0
    users_by_id = {user.id: user for user in db_session.query(User).all()}
    friend_pairs = {frozenset((row.user_a_id, row.user_b_id)) for row in friendships}
    for message in db_session.query(DirectMessage).all():
        assert message.sender_id != message.recipient_id
        # Messaging is friends-only in this app (routers/messaging.py) --
        # every seeded DM must actually be between two friends.
        assert frozenset((message.sender_id, message.recipient_id)) in friend_pairs
        assert message.created_at >= users_by_id[message.sender_id].created_at
        assert message.created_at >= users_by_id[message.recipient_id].created_at


def test_cold_seed_creates_listening_dj_and_mix_activity(db_session):
    _run(db_session)

    assert db_session.query(DJSession).count() >= 50
    assert db_session.query(Mix).count() >= 50
    assert db_session.query(MixSegment).count() > db_session.query(Mix).count()
    listening_count = db_session.query(ListeningEvent).count()
    assert listening_count > 1000  # "much more" than the ~50-user baseline

    users_by_id = {user.id: user for user in db_session.query(User).all()}
    for session in db_session.query(DJSession).all():
        assert session.created_at >= users_by_id[session.user_id].created_at
        assert session.status in {"playing", "stopped"}
    for event in db_session.query(ListeningEvent).all():
        assert event.started_at >= users_by_id[event.user_id].created_at
        assert event.seconds_listened >= 0
        # Mutually exclusive mix-vs-session context, matching
        # listening_service.create_event's real request-time invariant.
        assert (event.mix_id is not None) != (event.session_id is not None)


def test_cold_seed_analytics_reflect_the_seeded_listening_events(db_session):
    _run(db_session)

    user = (
        db_session.query(User)
        .join(ListeningEvent, ListeningEvent.user_id == User.id)
        .first()
    )
    events = db_session.query(ListeningEvent).filter_by(user_id=user.id).all()
    expected_seconds = sum(event.seconds_listened for event in events)

    identity = music_identity_service.build_music_identity(db_session, user.id, "all")

    # The analytics endpoint computes this live from the raw ListeningEvent
    # rows (see music_identity_service.py) -- this is the whole point of
    # seeding raw events instead of hand-writing analytics numbers.
    assert identity["summary"]["total_listening_seconds"] == expected_seconds
    assert identity["summary"]["artists_discovered"] > 0
    assert len(identity["artists"]) > 0
    assert len(identity["genres"]) > 0


def test_running_the_seeder_twice_creates_no_duplicates(db_session):
    first = _run(db_session)
    assert first["skipped"] is False

    user_count_after_first = db_session.query(User).count()
    post_count_after_first = db_session.query(ForumPost).count()
    listening_count_after_first = db_session.query(ListeningEvent).count()

    second = _run(db_session)
    assert second["skipped"] is True
    assert db_session.query(ColdSeedRun).filter_by(version=TEST_VERSION).count() == 1

    assert db_session.query(User).count() == user_count_after_first
    assert db_session.query(ForumPost).count() == post_count_after_first
    assert db_session.query(ListeningEvent).count() == listening_count_after_first


def test_cold_seed_never_touches_a_real_pre_existing_user(db_session):
    from app.core.security import hash_password

    real_user = User(username="realuser", email="real@example.com", hashed_password=hash_password("s3cret!!"))
    db_session.add(real_user)
    db_session.commit()
    real_user_id = real_user.id

    _run(db_session)

    preserved = db_session.get(User, real_user_id)
    assert preserved is not None
    assert preserved.username == "realuser"
    assert preserved.email == "real@example.com"
    # The seeded cohort must not have renamed/collided with the real account.
    assert db_session.query(User).filter_by(username="realuser").count() == 1


def test_main_seeds_by_default_when_enable_cold_seed_is_unset(monkeypatch, db_session):
    monkeypatch.delenv("ENABLE_COLD_SEED", raising=False)
    monkeypatch.delenv("COLD_SEED_VERSION", raising=False)
    monkeypatch.setattr("app.seed.SessionLocal", TestingSessionLocal)

    main()

    assert db_session.query(User).count() == TARGET_USER_COUNT
    assert db_session.query(ColdSeedRun).filter_by(version=config.DEFAULT_VERSION).count() == 1


def test_main_is_a_graceful_no_op_when_enable_cold_seed_is_false(monkeypatch, db_session):
    monkeypatch.setenv("ENABLE_COLD_SEED", "false")
    monkeypatch.setattr("app.seed.SessionLocal", TestingSessionLocal)

    main()  # must not raise

    assert db_session.query(User).count() == 0
    assert db_session.query(ColdSeedRun).count() == 0


def test_seed_demo_data_uses_configured_version_and_seed(monkeypatch, db_session):
    monkeypatch.setenv("COLD_SEED_VERSION", TEST_VERSION)
    monkeypatch.setenv("COLD_SEED_RANDOM_SEED", str(TEST_SEED))

    result = seed_demo_data(db_session)

    assert result["version"] == TEST_VERSION
    assert db_session.query(ColdSeedRun).filter_by(version=TEST_VERSION, random_seed=TEST_SEED).count() == 1
