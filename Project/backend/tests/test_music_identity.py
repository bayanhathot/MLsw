from datetime import datetime, timedelta, timezone

from conftest import register_and_login

from app.database.models.mix import Mix, MixSegment
from app.database.models.music_identity import ListeningEvent, UserMusicProfile


def create_test_mix(db_session, owner_id, *, published=True):
    mix = Mix(
        session_id=f"mix-test-{owner_id}",
        owner_id=owner_id,
        title="Night drive",
        prompt="energetic electronic night drive",
        status="published" if published else "draft",
    )
    db_session.add(mix)
    db_session.flush()
    segments = [
        MixSegment(
            mix_id=mix.id,
            position=1,
            title="Blue Hour",
            artist="Nova",
            audio_url="https://example.test/one.mp3",
            start_second=0,
            end_second=45,
            transition_to_next="crossfade",
            source="audius",
            source_track_id="nova-1",
            track_duration_seconds=180,
            genre="Electronic",
            vibe="Late Night",
        ),
        MixSegment(
            mix_id=mix.id,
            position=2,
            title="Signal",
            artist="Echo",
            audio_url="https://example.test/two.mp3",
            start_second=0,
            end_second=45,
            transition_to_next="end",
            source="audius",
            source_track_id="echo-1",
            track_duration_seconds=240,
            genre="Hip-Hop",
            vibe="Energetic",
        ),
    ]
    db_session.add_all(segments)
    db_session.commit()
    for segment in segments:
        db_session.refresh(segment)
    return mix, segments


def post_event(client, mix, segment, seconds, event_id, skipped=False):
    return client.post(
        "/listening-events",
        json={
            "client_event_id": event_id,
            "mix_id": mix.id,
            "segment_id": segment.id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "seconds_listened": seconds,
            "skipped": skipped,
        },
    )


def test_new_user_music_identity_is_private_by_default(client, db_session):
    user = register_and_login(client)
    profile = db_session.query(UserMusicProfile).filter_by(user_id=user["id"]).one()
    assert profile.is_public is False

    response = client.get("/users/me/music-identity")
    assert response.status_code == 200
    body = response.json()
    assert body["is_public"] is False
    assert body["summary"]["total_listening_seconds"] == 0
    assert body["segment_analytics"] == {
        "most_replayed_segment": None,
        "average_segment_length_seconds": None,
        "time_saved_seconds": 0,
        "segment_play_count": 0,
        "time_saved_play_count": 0,
    }
    assert body["artists"] == []
    assert body["listening_dna"]["status"] == "not_generated"


def test_listening_event_is_server_resolved_idempotent_and_aggregated(
    client, db_session
):
    user = register_and_login(client)
    mix, segments = create_test_mix(db_session, user["id"])

    first = post_event(client, mix, segments[0], 30, "evt-music-001", skipped=True)
    assert first.status_code == 201, first.text
    assert first.json()["artist_name"] == "Nova"
    assert first.json()["genre"] == "Electronic"
    assert first.json()["completion_ratio"] == 0.6667
    assert first.json()["track_duration_seconds"] == 180

    # Retrying the same client event is idempotent rather than double-counted.
    duplicate = post_event(client, mix, segments[0], 30, "evt-music-001", skipped=True)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]

    second = post_event(client, mix, segments[0], 45, "evt-music-002")
    third = post_event(client, mix, segments[1], 15, "evt-music-003", skipped=True)
    assert second.status_code == third.status_code == 201
    assert db_session.query(ListeningEvent).filter_by(user_id=user["id"]).count() == 3

    identity = client.get("/users/me/music-identity").json()
    assert identity["summary"]["total_listening_seconds"] == 90
    assert identity["summary"]["top_artist"]["name"] == "Nova"
    assert identity["summary"]["top_artist"]["seconds"] == 75
    assert identity["artists"][0]["percentage"] == 83.3
    assert identity["summary"]["top_genre"]["name"] == "Electronic"
    assert identity["summary"]["top_vibe"]["name"] == "Late Night"
    assert identity["segment_analytics"] == {
        "most_replayed_segment": {
            "segment_id": segments[0].id,
            "title": "Blue Hour",
            "artist": "Nova",
            "start_second": 0,
            "end_second": 45,
            "play_count": 2,
            "replay_count": 1,
            "seconds_listened": 75,
        },
        "average_segment_length_seconds": 45.0,
        "time_saved_seconds": 510,
        "segment_play_count": 3,
        "time_saved_play_count": 3,
    }
    assert identity["listening_trend"]
    assert identity["recent_listening"][0]["kind"] == "mix"

    # Every new proposal metric uses the exact same period filter as the
    # established Music Identity totals. Moving one of the replayed events
    # outside 30 days removes the replay winner and its time-saved amount.
    first_row = (
        db_session.query(ListeningEvent)
        .filter_by(client_event_id="evt-music-001")
        .one()
    )
    first_row.started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=40
    )
    db_session.commit()

    recent = client.get("/users/me/music-identity?period=30d").json()
    assert recent["summary"]["total_listening_seconds"] == 60
    assert recent["segment_analytics"] == {
        "most_replayed_segment": None,
        "average_segment_length_seconds": 45.0,
        "time_saved_seconds": 360,
        "segment_play_count": 2,
        "time_saved_play_count": 2,
    }


def test_listening_event_rejects_foreign_draft_and_mismatched_segment(
    client, second_client, db_session
):
    owner = register_and_login(client)
    other = register_and_login(second_client, "bob", "bob@example.com")
    draft, segments = create_test_mix(db_session, owner["id"], published=False)

    denied = post_event(second_client, draft, segments[0], 10, "evt-private-001")
    assert denied.status_code == 403

    other_mix, other_segments = create_test_mix(db_session, other["id"], published=True)
    mismatched = second_client.post(
        "/listening-events",
        json={
            "client_event_id": "evt-mismatch-001",
            "mix_id": other_mix.id,
            "segment_id": segments[0].id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "seconds_listened": 10,
            "skipped": True,
        },
    )
    assert mismatched.status_code == 422


def test_listening_event_rejects_future_timestamps(client, db_session):
    user = register_and_login(client)
    mix, segments = create_test_mix(db_session, user["id"])

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    started_in_future = client.post(
        "/listening-events",
        json={
            "client_event_id": "evt-future-start-001",
            "mix_id": mix.id,
            "segment_id": segments[0].id,
            "started_at": future,
            "seconds_listened": 10,
        },
    )
    assert started_in_future.status_code == 422
    assert "future" in started_in_future.json()["detail"].lower()

    now = datetime.now(timezone.utc).isoformat()
    ended_in_future = client.post(
        "/listening-events",
        json={
            "client_event_id": "evt-future-end-001",
            "mix_id": mix.id,
            "segment_id": segments[0].id,
            "started_at": now,
            "ended_at": future,
            "seconds_listened": 10,
        },
    )
    assert ended_in_future.status_code == 422
    assert "future" in ended_in_future.json()["detail"].lower()

    assert db_session.query(ListeningEvent).filter_by(user_id=user["id"]).count() == 0


def test_public_music_identity_privacy_and_public_profile_never_expose_email(
    client, second_client, db_session
):
    alice = register_and_login(client)
    mix, segments = create_test_mix(db_session, alice["id"])
    assert post_event(client, mix, segments[0], 20, "evt-public-001").status_code == 201

    register_and_login(second_client, "bob", "bob@example.com")
    private_view = second_client.get("/users/alice/music-identity")
    assert private_view.status_code == 200
    assert private_view.json() == {
        "username": "alice",
        "is_public": False,
        "music_identity": None,
    }

    public_profile = second_client.get("/users/alice/profile")
    assert public_profile.status_code == 200
    assert "email" not in public_profile.json()
    assert public_profile.json()["music_identity_public"] is False

    changed = client.patch("/users/me/music-identity/privacy", json={"is_public": True})
    assert changed.status_code == 200
    assert changed.json()["is_public"] is True

    visible = second_client.get("/users/alice/music-identity")
    assert visible.status_code == 200
    body = visible.json()
    assert body["is_public"] is True
    assert body["music_identity"]["summary"]["total_listening_seconds"] == 20
    assert "email" not in str(body).lower()

    assert (
        client.patch(
            "/users/me/music-identity/privacy", json={"is_public": False}
        ).json()["is_public"]
        is False
    )
    assert (
        second_client.get("/users/alice/music-identity").json()["music_identity"]
        is None
    )


def test_session_playback_can_be_recorded_without_client_supplied_track_metadata(
    client,
):
    register_and_login(client)
    session = client.post("/sessions/start", json={"prompt": "high energy gym"}).json()
    response = client.post(
        "/listening-events",
        json={
            "client_event_id": "evt-session-001",
            "session_id": session["id"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "seconds_listened": 12,
            "skipped": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["artist_name"] == "Cuemix AI DJ"
    assert body["vibe"] == "Gym energy"
    assert body["seconds_listened"] == 12
