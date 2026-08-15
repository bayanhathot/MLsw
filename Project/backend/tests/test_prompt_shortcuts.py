"""Unit and HTTP-level coverage for prompt_shortcuts.py's signature
clustering, N-use promotion threshold, and ranking -- plus GET
/users/me/prompt-shortcuts end to end. See test_sessions.py for the
existing UserPreference persistence/scoping tests this feature sits
alongside."""

from conftest import register_and_login

from app.database.models.user import User
from app.schemas import PromptIntent
from app.services import prompt_shortcuts


def _make_user(db_session, username: str) -> int:
    # prompt_shortcuts rows FK to a real users.id (foreign_keys=ON in the
    # test engine, see conftest.py), so direct service-level tests need an
    # actual User row, not just an arbitrary integer.
    user = User(username=username, email=f"{username}@example.test", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user.id


def _intent(**overrides) -> PromptIntent:
    base = dict(
        mood="energetic",
        energy="high",
        vocals="neutral",
        genres=["techno"],
        artist=None,
        artist_mode="none",
        search_query="gym energy please",
    )
    base.update(overrides)
    return PromptIntent(**base)


def test_signature_for_clusters_paraphrases_of_the_same_intent():
    # "gym energy please" and "make it energetic for the gym" both parse to
    # the same PromptIntent shape (prompt_parser.py) -- different
    # search_query text must not fragment the signature.
    a = _intent(search_query="gym energy please")
    b = _intent(search_query="make it energetic for the gym")
    assert prompt_shortcuts.signature_for(a) == prompt_shortcuts.signature_for(b)


def test_signature_for_is_order_independent_for_genres():
    a = _intent(genres=["techno", "house"])
    b = _intent(genres=["house", "techno"])
    assert prompt_shortcuts.signature_for(a) == prompt_shortcuts.signature_for(b)


def test_signature_for_distinguishes_required_artist_from_none():
    with_artist = _intent(artist="Nancy Ajram", artist_mode="required")
    without_artist = _intent(artist=None, artist_mode="none")
    assert prompt_shortcuts.signature_for(with_artist) != prompt_shortcuts.signature_for(
        without_artist
    )


def test_signature_for_does_not_key_on_which_artist_was_named():
    # Only *whether* an artist was required is part of the signature -- two
    # different required-artist requests still cluster together, matching
    # "how this user tends to use the app" rather than a per-artist grain.
    wassouf = _intent(artist="George Wassouf", artist_mode="required")
    ajram = _intent(artist="Nancy Ajram", artist_mode="required")
    assert prompt_shortcuts.signature_for(wassouf) == prompt_shortcuts.signature_for(ajram)


def test_record_prompt_then_top_shortcuts_requires_the_min_use_threshold(db_session, monkeypatch):
    monkeypatch.setattr(prompt_shortcuts, "PROMPT_SHORTCUT_MIN_USES", 3)
    intent = _intent()
    user_id = _make_user(db_session, "alice")

    prompt_shortcuts.record_prompt(db_session, user_id, "gym energy please", intent)
    prompt_shortcuts.record_prompt(db_session, user_id, "gym energy please", intent)
    db_session.commit()
    assert prompt_shortcuts.top_shortcuts(db_session, user_id) == []

    prompt_shortcuts.record_prompt(db_session, user_id, "make it energetic for the gym", intent)
    db_session.commit()
    shortcuts = prompt_shortcuts.top_shortcuts(db_session, user_id)
    assert len(shortcuts) == 1
    assert shortcuts[0].count == 3
    # Most-recent phrasing wins as the stored prompt text.
    assert shortcuts[0].prompt == "make it energetic for the gym"


def test_record_prompt_keeps_signatures_separate_per_user(db_session, monkeypatch):
    monkeypatch.setattr(prompt_shortcuts, "PROMPT_SHORTCUT_MIN_USES", 1)
    intent = _intent()
    alice_id = _make_user(db_session, "alice")
    bob_id = _make_user(db_session, "bob")
    prompt_shortcuts.record_prompt(db_session, alice_id, "gym energy please", intent)
    prompt_shortcuts.record_prompt(db_session, bob_id, "gym energy please", intent)
    db_session.commit()

    assert len(prompt_shortcuts.top_shortcuts(db_session, alice_id)) == 1
    assert len(prompt_shortcuts.top_shortcuts(db_session, bob_id)) == 1
    assert prompt_shortcuts.top_shortcuts(db_session, alice_id)[0].count == 1


def test_top_shortcuts_ranks_by_count_then_recency_and_caps_at_the_max(db_session, monkeypatch):
    monkeypatch.setattr(prompt_shortcuts, "PROMPT_SHORTCUT_MIN_USES", 1)
    monkeypatch.setattr(prompt_shortcuts, "MAX_PROMPT_SHORTCUTS", 2)
    user_id = _make_user(db_session, "alice")

    gym = _intent(mood="energetic", search_query="gym")
    focus = _intent(mood="focus", energy="low", search_query="focus")
    chill = _intent(mood="chill", energy="low", vocals="less", search_query="chill")

    for _ in range(5):
        prompt_shortcuts.record_prompt(db_session, user_id, "gym energy please", gym)
    for _ in range(2):
        prompt_shortcuts.record_prompt(db_session, user_id, "deep focus flow", focus)
    prompt_shortcuts.record_prompt(db_session, user_id, "chill evening", chill)
    db_session.commit()

    shortcuts = prompt_shortcuts.top_shortcuts(db_session, user_id)
    # Capped at MAX_PROMPT_SHORTCUTS (2), highest count first -- "chill"
    # (count 1) loses out to both "gym" (5) and "focus" (2).
    assert [row.prompt for row in shortcuts] == ["gym energy please", "deep focus flow"]


def test_prompt_shortcuts_endpoint_requires_login(client):
    assert client.get("/users/me/prompt-shortcuts").status_code == 401


def test_prompt_shortcuts_endpoint_is_empty_for_a_fresh_user(client):
    register_and_login(client)
    assert client.get("/users/me/prompt-shortcuts").json() == []


def test_session_creation_records_a_prompt_shortcut_for_logged_in_users(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(prompt_shortcuts, "PROMPT_SHORTCUT_MIN_USES", 2)
    register_and_login(client)

    client.post("/sessions/start", json={"prompt": "hard gym workout"})
    assert client.get("/users/me/prompt-shortcuts").json() == []

    client.post("/sessions/start", json={"prompt": "hard gym workout"})
    shortcuts = client.get("/users/me/prompt-shortcuts").json()
    assert len(shortcuts) == 1
    assert shortcuts[0]["prompt"] == "hard gym workout"
    assert shortcuts[0]["count"] == 2


def test_session_creation_does_not_record_a_shortcut_for_guests(client, monkeypatch):
    monkeypatch.setattr(prompt_shortcuts, "PROMPT_SHORTCUT_MIN_USES", 1)
    client.post("/sessions/start", json={"prompt": "hard gym workout"})
    # No identity to key off -- register afterward and confirm nothing
    # leaked in under some other row.
    register_and_login(client)
    assert client.get("/users/me/prompt-shortcuts").json() == []


def test_a_learned_preference_does_not_change_which_shortcut_signature_is_recorded(
    client, db_session, monkeypatch
):
    # record_prompt keys off the *raw* intent (before _apply_preference's
    # bias), not the one actually used to resolve this session -- otherwise
    # an unrelated learned preference could silently merge two genuinely
    # different prompts into one shortcut signature.
    monkeypatch.setattr(prompt_shortcuts, "PROMPT_SHORTCUT_MIN_USES", 1)
    user = register_and_login(client)
    session = client.post("/sessions/start", json={"prompt": "hard gym workout"}).json()
    client.post(f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"})

    client.post("/sessions/start", json={"prompt": "a balanced mix"})
    shortcuts = client.get("/users/me/prompt-shortcuts").json()
    assert any(row["prompt"] == "a balanced mix" for row in shortcuts)
