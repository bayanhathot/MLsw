from pathlib import Path

from conftest import register_and_login

from app.database.models.session import DJSession, UserPreference

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "zonix-demo.wav"
).read_bytes()

# Audius defaults to "nothing found" for every test via conftest.py's
# clean_database autouse fixture, so every session-creating test below
# reaches the local-catalog fallback deterministically and offline unless it
# explicitly overrides that with _patch_audius (below).


def _wassouf_tracks():
    """Three distinct real-shaped Audius candidates for one named artist --
    enough to prove a session rotates through more than one when advancing,
    not just repeats whatever it started on."""

    return [
        {
            "title": f"Wassouf Track {index}",
            "artist": "George Wassouf",
            "audio_url": f"https://audio.example/wassouf-{index}",
            "cover_url": None,
            "duration": 180,
            "source": "audius",
            "source_track_id": f"wassouf-{index}",
        }
        for index in range(1, 4)
    ]


def _patch_audius(monkeypatch, tracks):
    """Both the retrieval step and AudioRenderer's remote download are
    patched, matching tests/test_mixes.py's pattern, so a session with an
    Audius candidate renders a real, network-free composite instead of
    degrading to a pass-through because the fake example.test URLs aren't
    reachable."""

    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download", lambda url: _DEMO_WAV_BYTES
    )


def test_session_is_unique_persistent_and_feedback_changes_selection(client, db_session):
    first = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    second = client.post("/sessions/start", json={"prompt": "smooth focus music"})
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    # AudioRenderer actually rendered a trimmed clip rather than serving the
    # original file untouched.
    assert first.json()["audioUrl"].startswith("/api/media/renders/")
    assert first.json()["audioUrl"].endswith(".wav")
    assert db_session.query(DJSession).count() == 2

    session_id = first.json()["id"]
    feedback = client.post(
        f"/sessions/{session_id}/feedback", json={"feedback": "More energy"}
    )
    assert feedback.status_code == 200
    assert feedback.json()["selectedFeedback"] == "More energy"
    assert feedback.json()["vibeLabel"] == "Gym energy"
    assert client.post(f"/sessions/{session_id}/stop").status_code == 200
    assert client.post(
        f"/sessions/{session_id}/feedback", json={"feedback": "Smoother"}
    ).status_code == 409


def test_session_validation_and_unknown_ids(client):
    assert client.post("/sessions/start", json={"prompt": "   "}).status_code == 422
    assert client.post("/sessions/nope/feedback", json={"feedback": "Good vibe"}).status_code == 404
    assert client.post("/sessions/nope/stop").status_code == 404


def test_owned_session_is_private_and_preference_is_remembered(client, second_client, db_session):
    user = register_and_login(client)
    session = client.post("/sessions/start", json={"prompt": "anything"}).json()
    assert second_client.get(f"/sessions/{session['id']}").status_code == 403
    assert second_client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "Less vocals"}
    ).status_code == 403
    response = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "Less vocals"}
    )
    assert response.status_code == 200
    preference = db_session.query(UserPreference).filter_by(user_id=user["id"]).one()
    assert preference.feedback == "less_vocals"
    assert preference.score == 1
    assert client.get("/users/me/preferences").json() == [
        {"feedback": "less_vocals", "score": 1, "count": 1}
    ]
    # "less_vocals" biases the next neutral prompt's intent toward low
    # energy + fewer vocals, which lands on the same "focus" catalog bucket
    # the old hardcoded PREFERENCE_TRACKS mapping pointed it at.
    assert client.post("/sessions/start", json={"prompt": "a balanced mix"}).json()["vibeLabel"] == "Deep work focus"


def test_good_vibe_reinforces_the_track_that_was_playing(client, db_session):
    user = register_and_login(client)
    session = client.post("/sessions/start", json={"prompt": "hard gym workout"}).json()
    assert session["vibeLabel"] == "Gym energy"
    response = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "Good vibe"}
    )
    assert response.status_code == 200

    preference = db_session.query(UserPreference).filter_by(user_id=user["id"]).one()
    assert preference.feedback == "reinforce:high:neutral"
    neutral = client.post("/sessions/start", json={"prompt": "a balanced mix"})
    assert neutral.json()["vibeLabel"] == "Gym energy"


def test_named_artist_with_no_catalog_or_audius_match_is_reported_plainly(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks", lambda prompt, limit=5: []
    )
    response = client.post(
        "/sessions/start",
        json={"prompt": "play something by Zzzqx Nonexistent Artist Ptrxk"},
    )
    assert response.status_code == 422
    assert "catalog" in response.json()["detail"].lower()
    assert "audius" in response.json()["detail"].lower()


def test_named_artist_is_served_directly_by_audius_as_the_primary_retriever(
    client, monkeypatch, db_session
):
    """Audius is sessions' primary retriever now (matching Mixes), so a
    named artist absent from the tiny local catalog is served on the first
    try -- this is no longer a fallback."""

    _patch_audius(monkeypatch, _wassouf_tracks())
    response = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nowPlaying"]["artist"] == "George Wassouf"
    assert body["audioUrl"].startswith("/api/media/renders/")

    session = db_session.query(DJSession).filter_by(id=body["id"]).one()
    # AUDIUS_RETRIEVER defaults to "multi_query" (VIBE_RECOMMENDATION_DESIGN.md
    # section 8), so the primary retriever's name is "audius_multi_query", not
    # the older single-query retriever's plain "audius".
    assert session.retriever_name == "audius_multi_query"
    assert session.pipeline_trace_json["candidate_retriever"]["name"] == "audius_multi_query"
    assert session.pipeline_trace_json["candidate_retriever"]["fell_back"] is False


def test_generic_vibe_prompt_with_no_artist_now_reaches_audius_first(
    client, monkeypatch, db_session
):
    """The actual bug this priority swap fixes: a generic vibe/genre
    request (no named artist) used to hit the small local catalog and never
    reach Audius at all, because the catalog's no-artist path always
    returns *something* (a mood-bucket row, or any row as a last resort).
    Audius must now be tried first for this case too."""

    _patch_audius(monkeypatch, _wassouf_tracks())
    response = client.post(
        "/sessions/start", json={"prompt": "chill lofi beats for studying"}
    )
    assert response.status_code == 200
    body = response.json()
    # Not one of the 4 seeded local demo tracks.
    assert body["nowPlaying"]["artist"] == "George Wassouf"

    session = db_session.query(DJSession).filter_by(id=body["id"]).one()
    assert session.retriever_name == "audius_multi_query"
    assert session.pipeline_trace_json["candidate_retriever"]["fell_back"] is False


def test_when_audius_finds_nothing_catalog_serves_as_the_fallback(client, db_session):
    """The other half of the same priority: Audius defaults to no results
    via the autouse fixture above, so this exercises the fallback
    direction -- catalog only serves because Audius, tried first, came back
    empty, not because it was tried first."""

    response = client.post("/sessions/start", json={"prompt": "hard gym workout"})
    assert response.status_code == 200
    body = response.json()
    assert body["vibeLabel"] == "Gym energy"

    session = db_session.query(DJSession).filter_by(id=body["id"]).one()
    assert session.retriever_name == "catalog"
    assert session.pipeline_trace_json["candidate_retriever"]["name"] == "catalog"
    assert session.pipeline_trace_json["candidate_retriever"]["fell_back"] is True


def test_advance_continues_without_input_and_rotates_through_candidates(client, monkeypatch):
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()

    seen_titles = {session["nowPlaying"]["title"]}
    for _ in range(2):
        advanced = client.post(f"/sessions/{session['id']}/advance")
        assert advanced.status_code == 200
        seen_titles.add(advanced.json()["nowPlaying"]["title"])

    # All 3 candidates got a turn -- this isn't just replaying the same top
    # match every time.
    assert len(seen_titles) == 3

    # The pool is now exhausted (3 candidates, 3 already played this
    # session): advancing again must not error, and loops rather than
    # getting stuck -- "continuously advance ... looping indefinitely".
    looped = client.post(f"/sessions/{session['id']}/advance")
    assert looped.status_code == 200
    assert looped.json()["nowPlaying"]["title"] in seen_titles


def test_advance_persists_played_artists_alongside_played_track_keys(client, monkeypatch, db_session):
    # Validates the migration + session_manager wiring: played_artists_json
    # must grow in lockstep with played_track_keys_json (same length, same
    # cap), since it's what recent_artists is built from on the next
    # resolution -- the ranking-level diversity behavior itself is covered
    # in test_pipeline.py against _rank_by_metadata directly.
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    client.post(f"/sessions/{session['id']}/advance")
    client.post(f"/sessions/{session['id']}/advance")

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert row.played_artists_json == ["George Wassouf"] * len(row.played_track_keys_json)
    assert len(row.played_artists_json) == len(row.played_track_keys_json) == 3


def test_advance_rejects_a_stopped_session(client):
    session = client.post("/sessions/start", json={"prompt": "smooth focus music"}).json()
    assert client.post(f"/sessions/{session['id']}/stop").status_code == 200
    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 409


def test_advance_on_an_unknown_session_is_404(client):
    assert client.post("/sessions/nope/advance").status_code == 404


def test_advance_leaves_session_unchanged_when_nothing_matches(client, monkeypatch):
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()

    # Simulate Audius going unreachable mid-session for an artist that was
    # never in the catalog either -- advance must not error out a live
    # session, just leave it exactly where it was.
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks", lambda prompt, limit=5: []
    )
    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    assert response.json()["nowPlaying"]["title"] == session["nowPlaying"]["title"]


def test_feedback_keeps_using_audius_on_every_re_resolution(client, monkeypatch):
    """Coaching feedback must keep re-resolving through Audius on every
    request, not just the one that created the session -- not regress to a
    pinned retriever lookup."""

    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"}
    )
    assert feedback.status_code == 200
    assert feedback.json()["nowPlaying"]["artist"] == "George Wassouf"


def test_feedback_self_heals_from_catalog_fallback_to_audius(client, monkeypatch, db_session):
    """Requirement: the existing self-healing re-resolution still works with
    the swapped order. A session that started via the catalog fallback
    (Audius had nothing then) must pick Audius back up on the very next
    feedback-triggered re-resolution once Audius starts returning results --
    each resolution tries Audius fresh, nothing is pinned to how the session
    started."""

    session = client.post("/sessions/start", json={"prompt": "hard gym workout"}).json()
    # Served by the catalog fallback (Audius defaults to no results via the
    # autouse fixture above).
    assert session["vibeLabel"] == "Gym energy"

    _patch_audius(monkeypatch, _wassouf_tracks())
    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"}
    )
    assert feedback.status_code == 200
    assert feedback.json()["nowPlaying"]["artist"] == "George Wassouf"

    healed = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert healed.retriever_name == "audius_multi_query"
    assert healed.pipeline_trace_json["candidate_retriever"]["fell_back"] is False


def test_reasoning_and_next_direction_reflect_feedback_history(client):
    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert "Give feedback" in session["reasoning"]["nextDirection"]
    assert session["reasoning"]["selectedMoment"]
    assert session["reasoning"]["transitionPlan"]

    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "Smoother please"}
    ).json()
    assert "Smoother please" in feedback["reasoning"]["nextDirection"]
