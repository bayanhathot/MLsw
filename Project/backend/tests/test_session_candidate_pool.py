"""Unit coverage for session_candidate_pool.py's Lock-guarded cache. Also
exercised indirectly through the HTTP-level cache-reuse/invalidation tests
in test_sessions.py, but the fingerprint/TTL mechanics are most directly
verified here."""

import time

from app.schemas import PromptIntent, Track
from app.services import session_candidate_pool


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


def test_get_returns_none_for_a_missing_session():
    assert session_candidate_pool.get("unknown-session", ("A", "none", (), "balanced", "medium")) is None


def test_put_then_get_with_the_same_fingerprint_returns_the_cached_tracks():
    fingerprint = ("Artist", "required", ("lofi",), "chill", "high")
    tracks = [_track(source_track_id="1"), _track(source_track_id="2")]
    session_candidate_pool.put("session_a", fingerprint, tracks)
    assert session_candidate_pool.get("session_a", fingerprint) == tracks


def test_get_returns_none_when_the_fingerprint_no_longer_matches():
    fingerprint = ("Artist", "required", ("lofi",), "chill", "high")
    session_candidate_pool.put("session_b", fingerprint, [_track()])

    changed_fingerprint = ("Artist", "required", ("lofi",), "chill", "low")  # energy changed
    assert session_candidate_pool.get("session_b", changed_fingerprint) is None


def test_entry_expires_after_ttl(monkeypatch):
    monkeypatch.setattr(session_candidate_pool, "SESSION_CANDIDATE_POOL_TTL_SECONDS", 0.05)
    fingerprint = ("Artist", "required", ("lofi",), "chill", "high")
    tracks = [_track()]
    session_candidate_pool.put("session_c", fingerprint, tracks)
    assert session_candidate_pool.get("session_c", fingerprint) == tracks

    time.sleep(0.1)
    assert session_candidate_pool.get("session_c", fingerprint) is None


def test_pool_stays_bounded_under_more_insertions_than_the_max(monkeypatch):
    monkeypatch.setattr(session_candidate_pool, "SESSION_CANDIDATE_POOL_MAX_ENTRIES", 5)
    fingerprint = ("Artist", "required", ("lofi",), "chill", "high")

    for index in range(8):
        session_candidate_pool.put(f"session_bound_{index}", fingerprint, [_track()])

    assert len(session_candidate_pool._pools) == 5
    # Oldest-first eviction: the first 3 inserted made room for the last 5,
    # so they're gone and the most recent 5 remain.
    for index in range(3):
        assert f"session_bound_{index}" not in session_candidate_pool._pools
    for index in range(3, 8):
        assert f"session_bound_{index}" in session_candidate_pool._pools


def test_fingerprint_for_uses_sorted_genres_and_excludes_vocals_and_search_query():
    a = PromptIntent(
        mood="chill", energy="high", vocals="less", genres=["jazz", "lofi"],
        artist="X", artist_mode="required", search_query="one",
    )
    b = PromptIntent(
        mood="chill", energy="high", vocals="more", genres=["lofi", "jazz"],
        artist="X", artist_mode="required", search_query="two",
    )
    # Different vocals, different genre order, different search_query --
    # none of those affect build_queries/ranking, so the fingerprint must
    # be identical for both.
    assert session_candidate_pool.fingerprint_for(a) == session_candidate_pool.fingerprint_for(b)


def test_fingerprint_for_changes_when_energy_changes():
    a = PromptIntent(mood="chill", energy="high", vocals="neutral", genres=[], search_query="x")
    b = PromptIntent(mood="chill", energy="low", vocals="neutral", genres=[], search_query="x")
    assert session_candidate_pool.fingerprint_for(a) != session_candidate_pool.fingerprint_for(b)
