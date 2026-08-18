"""Targeted unit tests for audio_analysis.py's startup-time pending-analysis
requeue -- see app.main's lifespan and requeue_pending_analysis's own
docstring for why a plain "still pending" check is sufficient recovery
under the current analysis_status model (no intermediate "processing"
state exists, so a stranded row is always exactly "pending")."""

from queue import Full

from app.database.models.catalog import CatalogTrack
from app.services import audio_analysis
from app.services import upload_queue as uq_module


def _make_track(db_session, **overrides) -> CatalogTrack:
    fields = {
        "title": "Stranded Track",
        "artist": "Test Artist",
        "storage_name": "stranded.wav",
        "content_type": "audio/wav",
        "analysis_status": "pending",
    }
    fields.update(overrides)
    row = CatalogTrack(**fields)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_requeue_pending_analysis_resubmits_a_stranded_track(db_session, monkeypatch):
    track = _make_track(db_session)

    calls = []
    monkeypatch.setattr(uq_module.upload_queue, "submit_analysis", lambda track_id: calls.append(track_id))

    requeued = audio_analysis.requeue_pending_analysis()

    assert requeued == 1
    assert calls == [track.id]


def test_requeue_pending_analysis_ignores_non_pending_rows(db_session, monkeypatch):
    _make_track(db_session, title="Completed Track", analysis_status="completed")
    _make_track(db_session, title="Failed Track", analysis_status="failed")
    _make_track(db_session, title="Not Applicable Track", analysis_status="not_applicable")

    calls = []
    monkeypatch.setattr(uq_module.upload_queue, "submit_analysis", lambda track_id: calls.append(track_id))

    requeued = audio_analysis.requeue_pending_analysis()

    assert requeued == 0
    assert calls == []


def test_requeue_pending_analysis_continues_past_a_full_queue(db_session, monkeypatch):
    # One stuck submission (a full queue -- the same failure _dispatch_analysis
    # already tolerates for a normal upload) must not stop the rest of the
    # startup batch from being requeued.
    first = _make_track(db_session, title="First")
    second = _make_track(db_session, title="Second")

    calls = []

    def fake_submit_analysis(track_id):
        if track_id == first.id:
            raise Full
        calls.append(track_id)

    monkeypatch.setattr(uq_module.upload_queue, "submit_analysis", fake_submit_analysis)

    requeued = audio_analysis.requeue_pending_analysis()

    assert requeued == 1
    assert calls == [second.id]
