from conftest import register_and_login

from app.database.models.session import DJSession, UserPreference


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


def test_named_artist_with_no_catalog_match_is_reported_plainly(client):
    response = client.post(
        "/sessions/start",
        json={"prompt": "play something by Zzzqx Nonexistent Artist Ptrxk"},
    )
    assert response.status_code == 422
    assert "catalog" in response.json()["detail"].lower()


def test_reasoning_and_next_direction_reflect_feedback_history(client):
    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert "Give feedback" in session["reasoning"]["nextDirection"]
    assert session["reasoning"]["selectedMoment"]
    assert session["reasoning"]["transitionPlan"]

    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "Smoother please"}
    ).json()
    assert "Smoother please" in feedback["reasoning"]["nextDirection"]
