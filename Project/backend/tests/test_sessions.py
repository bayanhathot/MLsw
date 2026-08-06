def test_start_feedback_and_stop_demo_session(client):
    start_response = client.post(
        "/sessions/start",
        json={"prompt": "smooth focus music"},
    )

    assert start_response.status_code == 200
    session = start_response.json()
    assert session["id"] == "public-demo-session"
    assert session["prompt"] == "smooth focus music"
    assert session["audioUrl"].endswith("/static/audio/demo.mp3")

    feedback_response = client.post(
        f"/sessions/{session['id']}/feedback",
        json={"feedback": "More energy"},
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["prompt"] == "Feedback received in public demo mode."

    stop_response = client.post(f"/sessions/{session['id']}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"


def test_start_session_rejects_empty_prompt(client):
    response = client.post("/sessions/start", json={"prompt": ""})

    assert response.status_code == 422
