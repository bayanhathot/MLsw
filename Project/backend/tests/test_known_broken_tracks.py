"""Unit coverage for known_broken_tracks.py's DB-backed registry. Also
exercised indirectly through the session-integration tests in
test_sessions.py, but the TTL/upsert mechanics are most directly verified
here."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.session import KnownBrokenTrack
from app.schemas import Track
from app.services import known_broken_tracks


def _track(**overrides) -> Track:
    base = dict(
        source="audius",
        source_track_id="1",
        title="T",
        artist="A",
        album=None,
        audio_url="https://example.test/1",
        cover_url=None,
        duration_seconds=90,
        genre=None,
        vibe=None,
        vibe_label=None,
        tags=None,
        catalog_track_id=None,
        local_path=None,
    )
    base.update(overrides)
    return Track(**base)


def test_is_known_broken_is_false_for_a_track_with_no_entry(db_session):
    assert known_broken_tracks.is_known_broken(db_session, "audius:unknown") is False


def test_mark_broken_then_is_known_broken_returns_true(db_session):
    known_broken_tracks.mark_broken(db_session, _track(source_track_id="1"), "download_failed_http_403")
    db_session.commit()

    assert known_broken_tracks.is_known_broken(db_session, "audius:1") is True


def test_mark_broken_twice_upserts_rather_than_duplicating(db_session):
    track = _track(source_track_id="1")
    known_broken_tracks.mark_broken(db_session, track, "download_failed_http_403")
    known_broken_tracks.mark_broken(db_session, track, "decode_failed_CouldntDecodeError")
    db_session.commit()

    rows = db_session.query(KnownBrokenTrack).filter_by(track_key="audius:1").all()
    assert len(rows) == 1
    assert rows[0].failure_count == 2
    assert rows[0].fallback_reason == "decode_failed_CouldntDecodeError"


def test_is_known_broken_returns_false_and_deletes_a_row_past_its_ttl(db_session):
    stale_at = utc_now() - timedelta(seconds=known_broken_tracks.KNOWN_BROKEN_TRACK_TTL_SECONDS + 60)
    db_session.add(
        KnownBrokenTrack(
            track_key="audius:1",
            source="audius",
            source_track_id="1",
            title="T",
            fallback_reason="download_failed_http_403",
            failure_count=1,
            last_seen_at=stale_at,
        )
    )
    db_session.commit()

    assert known_broken_tracks.is_known_broken(db_session, "audius:1") is False
    db_session.commit()
    assert db_session.query(KnownBrokenTrack).filter_by(track_key="audius:1").one_or_none() is None


def test_mark_broken_recovers_when_a_concurrent_writer_wins_the_insert_race(db_session, monkeypatch):
    # prepare_next() and advance_session() can run concurrently for the same
    # session, each on its own DB Session -- both can discover the same
    # newly-broken track at nearly the same moment and both see "no row
    # yet" from their own db.get() before either commits. Simulated here by
    # forcing mark_broken's own initial db.get() to report None even though
    # a row already exists, so its INSERT hits a real primary-key conflict
    # -- the exact failure mode the try/except db.begin_nested() in
    # mark_broken exists to survive instead of raising IntegrityError up
    # into the caller's request (which previously surfaced as a 500).
    track_key = "audius:race"
    db_session.add(
        KnownBrokenTrack(
            track_key=track_key, source="audius", source_track_id="race",
            title="Existing", fallback_reason="download_failed_http_403", failure_count=1,
        )
    )
    db_session.commit()

    original_get = Session.get
    call_count = {"n": 0}

    def fake_get(self, model, key, *args, **kwargs):
        call_count["n"] += 1
        if model is KnownBrokenTrack and key == track_key and call_count["n"] == 1:
            return None
        return original_get(self, model, key, *args, **kwargs)

    monkeypatch.setattr(Session, "get", fake_get)

    track = _track(source_track_id="race")
    known_broken_tracks.mark_broken(db_session, track, "download_failed_http_503")

    rows = db_session.query(KnownBrokenTrack).filter_by(track_key=track_key).all()
    assert len(rows) == 1
    assert rows[0].fallback_reason == "download_failed_http_503"


def test_is_known_broken_returns_true_for_a_row_still_within_ttl(db_session):
    recent_at = utc_now() - timedelta(seconds=known_broken_tracks.KNOWN_BROKEN_TRACK_TTL_SECONDS - 60)
    db_session.add(
        KnownBrokenTrack(
            track_key="audius:1",
            source="audius",
            source_track_id="1",
            title="T",
            fallback_reason="download_failed_http_403",
            failure_count=1,
            last_seen_at=recent_at,
        )
    )
    db_session.commit()

    assert known_broken_tracks.is_known_broken(db_session, "audius:1") is True
