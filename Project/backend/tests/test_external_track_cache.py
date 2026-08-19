"""Prompt 3 (batched lookup, atomic first-encounter dispatch, dedup, retry
cap) and Prompt 4 (fingerprint verification) for
pipeline/external_track_cache.py."""

from sqlalchemy.orm import Session

from app.database.models.external_track import ExternalTrack
from app.schemas import Track
from app.services import audio_analysis
from app.services.pipeline import external_track_cache as etc
from app.services.upload_queue import upload_queue as uq


def _track(**overrides) -> Track:
    base = dict(
        source="audius", source_track_id="1", title="T", artist="A", album=None,
        audio_url="https://example.test/1", cover_url=None, duration_seconds=90,
        genre=None, vibe=None, vibe_label=None, tags=None, catalog_track_id=None,
        local_path=None,
    )
    base.update(overrides)
    return Track(**base)


def _count_external_track_queries(monkeypatch):
    """Counts Session.query(ExternalTrack, ...) call sites actually
    invoked -- a direct, environment-independent way to verify the
    enrichment lookup itself is one batched call for the whole candidate
    set, not one per candidate (a raw SQL-statement listener proved
    unreliable against this test DB's connection pooling)."""

    count = {"n": 0}
    original_query = Session.query

    def counting_query(self, *entities, **kwargs):
        if any(entity is ExternalTrack for entity in entities):
            count["n"] += 1
        return original_query(self, *entities, **kwargs)

    monkeypatch.setattr(Session, "query", counting_query)
    return count


def test_enrich_and_dispatch_is_a_no_op_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(etc, "AUDIUS_ANALYSIS_CACHE_ENABLED", False)
    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    track = _track()
    etc.enrich_and_dispatch(db_session, [track])

    assert track.external_track_id is None
    assert calls == []
    assert db_session.query(ExternalTrack).count() == 0


def test_enrich_and_dispatch_creates_and_dispatches_a_brand_new_candidate(db_session, monkeypatch):
    monkeypatch.setattr(etc, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    track = _track(source_track_id="new-1", title="Brand New", artist="Someone")
    etc.enrich_and_dispatch(db_session, [track])

    assert track.external_track_id is not None
    row = db_session.query(ExternalTrack).filter_by(id=track.external_track_id).first()
    assert row is not None
    assert row.source == "audius"
    assert row.external_id == "new-1"
    assert row.analysis_status == "pending"
    assert calls == [row.id]


def test_enrich_and_dispatch_skips_dispatch_for_an_already_pending_row(db_session, monkeypatch):
    monkeypatch.setattr(etc, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    track = _track(source_track_id="dup-1")
    etc.enrich_and_dispatch(db_session, [track])
    assert len(calls) == 1

    # A second encounter of the same (source, external_id) -- e.g. a
    # different session hitting the same still-pending Audius track --
    # must NOT enqueue a second job (Prompt 3's own dedup requirement).
    second_track = _track(source_track_id="dup-1")
    etc.enrich_and_dispatch(db_session, [second_track])

    assert len(calls) == 1
    assert second_track.external_track_id == track.external_track_id


def test_enrich_and_dispatch_uses_exactly_one_query_for_a_mixed_candidate_set(db_session, monkeypatch):
    monkeypatch.setattr(etc, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: None)

    # One already-cached row, plus two brand-new candidates (no conflicting
    # row for either -- so _create_or_get_existing's own IntegrityError-
    # recovery query, exercised separately below, never fires here) and one
    # catalog (non-Audius) candidate that must be ignored entirely.
    existing = ExternalTrack(
        source="audius", external_id="cached-1", title="T", artist="A",
        analysis_status="completed", analysis_version=audio_analysis.ANALYSIS_VERSION,
    )
    db_session.add(existing)
    db_session.commit()

    candidates = [
        _track(source_track_id="cached-1"),
        _track(source_track_id="fresh-1"),
        _track(source_track_id="fresh-2"),
        _track(source="catalog", source_track_id="99", catalog_track_id=99),
    ]

    count = _count_external_track_queries(monkeypatch)
    etc.enrich_and_dispatch(db_session, candidates)

    # Exactly one query for the whole candidate set's lookup -- not one per
    # candidate (which would be 3, for the 3 Audius candidates).
    assert count["n"] == 1
    assert candidates[0].external_track_id == existing.id
    assert candidates[1].external_track_id is not None
    assert candidates[2].external_track_id is not None
    assert candidates[3].external_track_id is None  # catalog candidate untouched


def test_create_or_get_existing_recovers_when_a_concurrent_insert_already_won(db_session):
    # Simulates the real race Prompt 3 step 5 asks to be proven, not just
    # written: this session's own insert hits a genuine UNIQUE constraint
    # violation because a "concurrent" request's row is already committed
    # -- mirrors known_broken_tracks.mark_broken's own race test (see
    # test_known_broken_tracks.py) rather than inventing a new pattern.
    winner = ExternalTrack(source="audius", external_id="race-1", title="Winner", artist="A")
    db_session.add(winner)
    db_session.commit()

    loser_track = _track(source_track_id="race-1", title="Loser view of the same track")
    row, won = etc._create_or_get_existing(db_session, loser_track)

    assert won is False
    assert row is not None
    assert row.id == winner.id
    assert db_session.query(ExternalTrack).filter_by(external_id="race-1").count() == 1


def test_enrich_and_dispatch_retries_a_failed_row_up_to_the_attempt_cap(db_session, monkeypatch):
    monkeypatch.setattr(etc, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_analysis, "EXTERNAL_ANALYSIS_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(etc, "EXTERNAL_ANALYSIS_MAX_ATTEMPTS", 2)
    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    row = ExternalTrack(
        source="audius", external_id="fail-1", title="T", artist="A",
        analysis_status="failed", analysis_attempt_count=1,
    )
    db_session.add(row)
    db_session.commit()

    etc.enrich_and_dispatch(db_session, [_track(source_track_id="fail-1")])
    assert calls == [row.id]  # attempt_count (1) < cap (2) -- retried

    row.analysis_status = "failed"
    row.analysis_attempt_count = 2
    db_session.commit()
    calls.clear()

    etc.enrich_and_dispatch(db_session, [_track(source_track_id="fail-1")])
    assert calls == []  # at the cap -- not retried again


def test_enrich_and_dispatch_leaves_a_version_stale_row_trusted_but_reprocesses_it(db_session, monkeypatch):
    # A "completed" row with an old analysis_version stays playable with
    # its existing (still-correct) data -- analysis_status is deliberately
    # NOT flipped away from "completed" -- while a fresh pass is still
    # dispatched in the background (see external_track_cache.py's own
    # module docstring for why this differs from the is_stale/failed cases).
    monkeypatch.setattr(etc, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    row = ExternalTrack(
        source="audius", external_id="old-version-1", title="T", artist="A",
        analysis_status="completed", analysis_version="v1", bpm=120.0,
    )
    db_session.add(row)
    db_session.commit()

    etc.enrich_and_dispatch(db_session, [_track(source_track_id="old-version-1")])

    db_session.refresh(row)
    assert row.analysis_status == "completed"  # still trusted
    assert row.bpm == 120.0  # untouched
    assert calls == [row.id]  # but reprocessing was dispatched


def test_verify_fingerprint_matching_hash_writes_nothing(db_session, monkeypatch):
    row = ExternalTrack(
        source="audius", external_id="verify-1", title="T", artist="A",
        analysis_status="completed", audio_sha256="abc123",
    )
    db_session.add(row)
    db_session.commit()
    track = _track(source_track_id="verify-1", external_track_id=row.id)

    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))
    original_commit = db_session.commit
    commit_calls = {"n": 0}

    def counting_commit():
        commit_calls["n"] += 1
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    etc.verify_fingerprint(db_session, track, "abc123")

    db_session.refresh(row)
    assert row.is_stale is False
    assert row.audio_sha256 == "abc123"
    assert calls == []
    assert commit_calls["n"] == 0  # a match is a true no-op -- no DB write at all


def test_verify_fingerprint_mismatch_marks_stale_and_dispatches_reanalysis(db_session, monkeypatch):
    row = ExternalTrack(
        source="audius", external_id="verify-2", title="T", artist="A",
        analysis_status="completed", audio_sha256="old-hash", bpm=120.0,
    )
    db_session.add(row)
    db_session.commit()
    track = _track(source_track_id="verify-2", external_track_id=row.id)

    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    etc.verify_fingerprint(db_session, track, "new-hash-the-audio-actually-changed")

    db_session.refresh(row)
    assert row.is_stale is True
    assert row.audio_sha256 == "old-hash"  # left untouched, per Prompt 4 step 3
    assert row.bpm == 120.0  # every other analysis field also untouched
    assert row.analysis_status == "pending"
    assert calls == [row.id]


def test_verify_fingerprint_is_a_no_op_without_a_cached_row_or_a_fetched_hash(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(uq, "submit_external_analysis", lambda track_id: calls.append(track_id))

    # No external_track_id at all (never cached).
    etc.verify_fingerprint(db_session, _track(external_track_id=None), "some-hash")
    # No audio_sha256 (local_path load, or a pass-through render).
    etc.verify_fingerprint(db_session, _track(external_track_id=1), None)

    assert calls == []
