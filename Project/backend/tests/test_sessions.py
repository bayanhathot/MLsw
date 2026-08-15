import time
from pathlib import Path

from conftest import register_and_login

from app.database.models.session import DJSession, UserPreference
from app.services import session_manager
from app.services.pipeline.audius_retriever import MultiQueryAudiusRetriever

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
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


def _many_wassouf_tracks(count):
    """Same shape as _wassouf_tracks, but a caller-chosen count -- tests of
    the candidate-pool cache's exhaustion threshold need a pool big enough
    that a couple of advance() calls don't run it down to a forced refresh
    on their own."""

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
        for index in range(1, count + 1)
    ]


def _count_retrieve_calls(monkeypatch):
    """Wraps MultiQueryAudiusRetriever.retrieve so tests can assert on how
    many times it was *actually* called -- the session_candidate_pool cache
    exists precisely to make that number lower than the number of
    start/feedback/advance requests."""

    calls = {"count": 0}
    original_retrieve = MultiQueryAudiusRetriever.retrieve

    def counting_retrieve(self, *args, **kwargs):
        calls["count"] += 1
        return original_retrieve(self, *args, **kwargs)

    monkeypatch.setattr(MultiQueryAudiusRetriever, "retrieve", counting_retrieve)
    return calls


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
        "app.services.pipeline.audio_renderer._download", lambda url: (_DEMO_WAV_BYTES, None)
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


def test_preference_is_not_applied_when_the_new_prompt_names_an_artist(
    client, db_session, monkeypatch
):
    # A learned preference only ever biases a *neutral* prompt -- one naming
    # an artist is never neutral, regardless of how strong the preference
    # is, since the user asked for something specific this time.
    user = register_and_login(client)
    session = client.post("/sessions/start", json={"prompt": "hard gym workout"}).json()
    client.post(f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"})
    preference = db_session.query(UserPreference).filter_by(user_id=user["id"]).one()
    assert preference.feedback == "more_energy"
    assert preference.score > 0

    _patch_audius(monkeypatch, _wassouf_tracks())
    named = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    row = db_session.query(DJSession).filter_by(id=named["id"]).one()
    assert row.intent_json["energy"] == "medium"


def test_preference_is_not_applied_when_the_new_prompt_sets_explicit_energy(client, db_session):
    # Same scoping rule from the other direction: a prompt with its own
    # explicit energy word is never neutral either, so a learned
    # more_energy preference must not override what this prompt actually
    # asked for.
    user = register_and_login(client)
    session = client.post("/sessions/start", json={"prompt": "hard gym workout"}).json()
    client.post(f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"})
    preference = db_session.query(UserPreference).filter_by(user_id=user["id"]).one()
    assert preference.feedback == "more_energy"
    assert preference.score > 0

    chill = client.post("/sessions/start", json={"prompt": "chill vibes for reading"}).json()
    row = db_session.query(DJSession).filter_by(id=chill["id"]).one()
    assert row.intent_json["energy"] == "low"


def test_feedback_mutates_intent_but_never_touches_original_intent(client, db_session):
    session = client.post("/sessions/start", json={"prompt": "a balanced mix"}).json()
    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert row.original_intent_json["energy"] == "medium"
    assert row.intent_json["energy"] == "medium"

    response = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"}
    )
    assert response.status_code == 200

    db_session.refresh(row)
    # intent_json mutates on feedback...
    assert row.intent_json["energy"] == "high"
    # ...but original_intent_json, set once at creation, never does.
    assert row.original_intent_json["energy"] == "medium"


def test_create_session_skips_a_candidate_whose_audio_cannot_be_rendered(client, monkeypatch, db_session):
    # A track that ranks first but whose audio genuinely can't be fetched
    # (e.g. Audius returning a 4xx for that specific track) must not become
    # a dead pass-through -- the next-ranked candidate should be tried
    # instead, same as if the first one simply hadn't been offered.
    tracks = [
        {
            "title": "Broken Track", "artist": "Artist A",
            "audio_url": "https://audio.example/broken", "source_track_id": "broken-1",
            "duration": 100, "source": "audius",
        },
        {
            "title": "Good Track", "artist": "Artist B",
            "audio_url": "https://audio.example/good", "source_track_id": "good-1",
            "duration": 100, "source": "audius",
        },
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )

    def fake_download(url):
        if url.endswith("/broken"):
            return None, "download_failed_http_403"
        return _DEMO_WAV_BYTES, None

    monkeypatch.setattr("app.services.pipeline.audio_renderer._download", fake_download)

    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert session["nowPlaying"]["title"] == "Good Track"
    assert session["nowPlaying"]["artist"] == "Artist B"

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    audio_trace = row.pipeline_trace_json["audio_renderer"]
    assert audio_trace["is_pass_through"] is False
    assert len(audio_trace["skipped_tracks"]) == 1
    assert audio_trace["skipped_tracks"][0]["source_track_id"] == "broken-1"
    assert audio_trace["skipped_tracks"][0]["fallback_reason"] == "download_failed_http_403"


def test_create_session_rescues_a_render_with_the_catalog_when_every_audius_candidate_fails(
    client, monkeypatch, db_session
):
    # A systemically broken source (or a whole pool of unavailable tracks)
    # must not turn one resolution into an unbounded string of doomed
    # download attempts -- capped at AUDIO_RENDER_RETRY_LIMIT -- nor land the
    # session on a dead pass-through when a real fallback source (the local
    # catalog, never a remote fetch) can actually produce playable audio.
    tracks = [
        {
            "title": f"Broken {i}", "artist": "Artist",
            "audio_url": f"https://audio.example/broken-{i}", "source_track_id": f"broken-{i}",
            "duration": 100, "source": "audius",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download",
        lambda url: (None, "download_failed_http_403"),
    )

    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    # None of the 5 broken Audius tracks -- a real catalog track instead.
    assert session["nowPlaying"]["title"] not in {f"Broken {i}" for i in range(5)}

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    audio_trace = row.pipeline_trace_json["audio_renderer"]
    assert audio_trace["is_pass_through"] is False
    # All 5 broken Audius candidates were tried (well under
    # AUDIO_RENDER_RETRY_LIMIT's default, the full candidate pool) and
    # discarded in favor of the catalog rescue.
    assert len(audio_trace["skipped_tracks"]) == 5
    assert row.pipeline_trace_json["candidate_retriever"]["fell_back"] is True
    assert row.pipeline_trace_json["candidate_retriever"]["name"] == "catalog"


def test_create_session_keeps_the_pass_through_when_not_even_the_catalog_can_rescue_it(
    client, monkeypatch, db_session
):
    # The catalog rescue only helps when it actually has something to offer:
    # a named artist absent from the tiny local demo catalog still has
    # nowhere left to fall through to, so the session must land on the
    # retry-capped Audius attempt's honest pass-through, same as before the
    # rescue existed.
    tracks = [
        {
            "title": f"Broken {i}", "artist": "Nancy Ajram",
            "audio_url": f"https://audio.example/broken-{i}", "source_track_id": f"broken-{i}",
            "duration": 100, "source": "audius",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download",
        lambda url: (None, "download_failed_http_403"),
    )

    session = client.post(
        "/sessions/start", json={"prompt": "play something by Nancy Ajram"}
    ).json()
    # All 5 candidates were genuinely tried (not capped early) -- the last
    # of them is the kept, honest pass-through.
    assert session["nowPlaying"]["title"] == "Broken 4"

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    audio_trace = row.pipeline_trace_json["audio_renderer"]
    assert audio_trace["is_pass_through"] is True
    assert len(audio_trace["skipped_tracks"]) == 4
    assert row.pipeline_trace_json["candidate_retriever"]["fell_back"] is False


def test_audio_render_retry_limit_still_caps_attempts_when_lowered(client, monkeypatch, db_session):
    # AUDIO_RENDER_RETRY_LIMIT defaults to the whole candidate pool now
    # (never stop early while untried real candidates remain), but it must
    # still act as a hard safety cap when an operator lowers it.
    monkeypatch.setattr(session_manager, "AUDIO_RENDER_RETRY_LIMIT", 2)
    tracks = [
        {
            "title": f"Broken {i}", "artist": "Nancy Ajram",
            "audio_url": f"https://audio.example/broken-{i}", "source_track_id": f"broken-{i}",
            "duration": 100, "source": "audius",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download",
        lambda url: (None, "download_failed_http_403"),
    )

    session = client.post(
        "/sessions/start", json={"prompt": "play something by Nancy Ajram"}
    ).json()
    assert session["nowPlaying"]["title"] == "Broken 1"

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert len(row.pipeline_trace_json["audio_renderer"]["skipped_tracks"]) == 1


def test_audio_render_time_budget_stops_retries_even_under_the_count_cap(
    client, monkeypatch, db_session
):
    # A genuinely unreachable source can hang for the full remote timeout on
    # every single attempt, unlike a fast-failing HTTP error -- the shared
    # wall-clock budget must still cut retries short well before
    # AUDIO_RENDER_RETRY_LIMIT's (much larger) candidate-count cap would.
    monkeypatch.setattr(session_manager, "AUDIO_RENDER_TIME_BUDGET_SECONDS", 0.0)
    tracks = [
        {
            "title": f"Broken {i}", "artist": "Nancy Ajram",
            "audio_url": f"https://audio.example/broken-{i}", "source_track_id": f"broken-{i}",
            "duration": 100, "source": "audius",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download",
        lambda url: (None, "download_failed_http_403"),
    )

    session = client.post(
        "/sessions/start", json={"prompt": "play something by Nancy Ajram"}
    ).json()
    # A zero time budget means the very first attempt already exceeds the
    # deadline once it returns -- exactly one attempt is made, not all 5.
    assert session["nowPlaying"]["title"] == "Broken 0"

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert row.pipeline_trace_json["audio_renderer"]["skipped_tracks"] == []


def test_a_previously_known_broken_track_is_skipped_without_a_download_attempt(
    client, monkeypatch, db_session
):
    # A track already recorded as broken by an earlier resolution (possibly
    # from a different session entirely) should never even attempt a
    # download -- it's skipped straight away, same as if the retry loop had
    # already tried and discarded it, but without paying the network cost.
    from app.database.models.session import KnownBrokenTrack

    tracks = [
        {
            "title": "Previously Broken", "artist": "Artist A",
            "audio_url": "https://audio.example/broken", "source_track_id": "broken-1",
            "duration": 100, "source": "audius",
        },
        {
            "title": "Good Track", "artist": "Artist B",
            "audio_url": "https://audio.example/good", "source_track_id": "good-1",
            "duration": 100, "source": "audius",
        },
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )

    db_session.add(
        KnownBrokenTrack(
            track_key="audius:broken-1",
            source="audius",
            source_track_id="broken-1",
            title="Previously Broken",
            fallback_reason="download_failed_http_403",
            failure_count=3,
        )
    )
    db_session.commit()

    download_calls = []

    def fake_download(url):
        download_calls.append(url)
        return _DEMO_WAV_BYTES, None

    monkeypatch.setattr("app.services.pipeline.audio_renderer._download", fake_download)

    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert session["nowPlaying"]["title"] == "Good Track"
    assert download_calls == ["https://audio.example/good"]

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    audio_trace = row.pipeline_trace_json["audio_renderer"]
    assert audio_trace["skipped_tracks"] == [
        {
            "source": "audius",
            "source_track_id": "broken-1",
            "title": "Previously Broken",
            "fallback_reason": "known_broken",
        }
    ]


def test_a_render_failure_persists_a_known_broken_track_row(client, monkeypatch, db_session):
    # The flip side: when AudioRenderer genuinely fails on a candidate
    # during a normal resolution, that failure must be persisted so a
    # *future* resolution (this session or another) can skip it outright.
    from app.database.models.session import KnownBrokenTrack

    tracks = [
        {
            "title": "Broken Track", "artist": "Artist A",
            "audio_url": "https://audio.example/broken", "source_track_id": "broken-1",
            "duration": 100, "source": "audius",
        },
        {
            "title": "Good Track", "artist": "Artist B",
            "audio_url": "https://audio.example/good", "source_track_id": "good-1",
            "duration": 100, "source": "audius",
        },
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )

    def fake_download(url):
        if url.endswith("/broken"):
            return None, "download_failed_http_403"
        return _DEMO_WAV_BYTES, None

    monkeypatch.setattr("app.services.pipeline.audio_renderer._download", fake_download)

    client.post("/sessions/start", json={"prompt": "chill lofi beats"})

    row = db_session.query(KnownBrokenTrack).filter_by(track_key="audius:broken-1").one()
    assert row.fallback_reason == "download_failed_http_403"
    assert row.failure_count == 1


def test_known_broken_track_past_its_ttl_is_tried_again(client, monkeypatch, db_session):
    from datetime import timedelta

    from app.core.time import utc_now
    from app.database.models.session import KnownBrokenTrack
    from app.services import known_broken_tracks

    tracks = [
        {
            "title": "Old News", "artist": "Artist A",
            "audio_url": "https://audio.example/oldnews", "source_track_id": "old-1",
            "duration": 100, "source": "audius",
        },
    ]
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )

    stale_at = utc_now() - timedelta(seconds=known_broken_tracks.KNOWN_BROKEN_TRACK_TTL_SECONDS + 60)
    db_session.add(
        KnownBrokenTrack(
            track_key="audius:old-1",
            source="audius",
            source_track_id="old-1",
            title="Old News",
            fallback_reason="download_failed_http_403",
            failure_count=1,
            last_seen_at=stale_at,
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download", lambda url: (_DEMO_WAV_BYTES, None)
    )

    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert session["nowPlaying"]["title"] == "Old News"


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


def test_advance_reuses_the_cached_candidate_pool_when_intent_is_unchanged(client, monkeypatch):
    # 10 candidates -- comfortably more than _CANDIDATE_POOL_REFRESH_THRESHOLD
    # (3) even after a couple of advances, so this isolates "does an
    # unchanged intent reuse the cache" from the separate exhaustion-refresh
    # behavior covered below.
    _patch_audius(monkeypatch, _many_wassouf_tracks(10))
    calls = _count_retrieve_calls(monkeypatch)

    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1  # create_session's one real retrieval

    assert client.post(f"/sessions/{session['id']}/advance").status_code == 200
    assert client.post(f"/sessions/{session['id']}/advance").status_code == 200

    # Both advances reused the pool cached at creation -- the intent never
    # changed, so no additional retrieve() call was needed.
    assert calls["count"] == 1


def test_advance_refreshes_the_pool_once_fresh_candidates_drop_below_threshold(client, monkeypatch):
    # Exactly 3 candidates (== _CANDIDATE_POOL_REFRESH_THRESHOLD): after the
    # first one plays at creation, only 2 unplayed candidates remain in the
    # cached pool -- below the threshold -- so the very next advance() must
    # force a real retrieval even though the intent hasn't changed at all.
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)

    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    assert client.post(f"/sessions/{session['id']}/advance").status_code == 200
    assert calls["count"] == 2  # forced refresh: only 2 fresh candidates were left


def test_feedback_that_changes_energy_invalidates_the_cached_pool(client, monkeypatch):
    _patch_audius(monkeypatch, _many_wassouf_tracks(10))
    calls = _count_retrieve_calls(monkeypatch)

    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"}
    )
    assert feedback.status_code == 200
    # "More energy" mutates intent.energy, which is part of the cache
    # fingerprint -- the mutated intent can never hit the pool cached under
    # the old fingerprint, forcing a real retrieval rather than serving a
    # pool ranked for the session's original (lower-energy) intent.
    assert calls["count"] == 2


# --- Phase C: prepare-next / prefetch (PHASE_C_PREFETCH_DESIGN.md) --------


def test_prepare_next_populates_prepared_next_json_without_touching_live_fields(
    client, monkeypatch, db_session
):
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    live_now_playing = row.now_playing_json
    live_reasoning = row.reasoning_json
    live_intent = row.intent_json
    assert row.prepared_next_json is None

    response = client.post(f"/sessions/{session['id']}/prepare-next")
    assert response.status_code == 200
    body = response.json()
    assert body["prepared"] is True
    assert body["audioUrl"]

    db_session.refresh(row)
    assert row.prepared_next_json is not None
    assert row.prepared_next_json["now_playing"]["audio_url"] == body["audioUrl"]
    # Nothing the session currently reports as playing was touched.
    assert row.now_playing_json == live_now_playing
    assert row.reasoning_json == live_reasoning
    assert row.intent_json == live_intent


def test_advance_consumes_a_valid_prepared_item_without_calling_the_retriever_again(
    client, monkeypatch, db_session
):
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    prep = client.post(f"/sessions/{session['id']}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True
    assert calls["count"] == 2  # prepare-next's own resolution

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    prepared_audio_url = row.prepared_next_json["now_playing"]["audio_url"]

    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    assert response.json()["audioUrl"] == prepared_audio_url
    # Fast path: consuming the prepared item made no additional retrieve() call.
    assert calls["count"] == 2

    db_session.refresh(row)
    assert row.prepared_next_json is None  # consumed and cleared


def test_advance_does_a_real_resolution_when_no_prepared_item_exists(client, monkeypatch, db_session):
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert row.prepared_next_json is None

    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    assert calls["count"] == 2


def test_advance_does_a_real_resolution_when_the_prepared_item_has_expired(client, monkeypatch):
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    monkeypatch.setattr(session_manager, "PREPARED_NEXT_TTL_SECONDS", 0.05)

    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    prep = client.post(f"/sessions/{session['id']}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True
    assert calls["count"] == 2

    time.sleep(0.1)
    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    # The prepared item had aged past PREPARED_NEXT_TTL_SECONDS, so this fell
    # through to a real resolution instead of consuming stale state.
    assert calls["count"] == 3


def test_advance_does_a_real_resolution_when_prepared_fingerprint_mismatches(
    client, monkeypatch, db_session
):
    # Simulates PHASE_C_PREFETCH_DESIGN.md section 3.5's race directly: a
    # prepared item sitting in the row with a fingerprint that no longer
    # matches the session's current intent (e.g. intent changed by some
    # other path after this was prepared) -- advance_session's own
    # fingerprint check has to catch this, not just apply_feedback's
    # explicit clear (covered separately below).
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    row.prepared_next_json = {
        "track_key": "audius:mismatched-1",
        "artist": "Someone Else",
        "now_playing": {},
        "reasoning": {},
        "pipeline_trace": {},
        "fingerprint": ["Someone Else", "required", [], "chill", "low"],
        "prepared_at": time.monotonic(),
    }
    db_session.commit()

    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    assert calls["count"] == 2  # the mismatched prepared item was ignored


def test_feedback_that_changes_energy_clears_prepared_next_and_forces_real_resolution(
    client, monkeypatch, db_session
):
    # 10 candidates, same as the pool-cache-reuse test above: with only 1
    # track played so far, prepare-next's own _resolve_and_render reuses the
    # still-warm session_candidate_pool rather than calling the retriever
    # again -- that's the pool cache working as intended (section 3.2 notes
    # this explicitly: "a warm candidate pool means this is often nearly
    # free"), not something this test is exercising.
    _patch_audius(monkeypatch, _many_wassouf_tracks(10))
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    prep = client.post(f"/sessions/{session['id']}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True
    assert calls["count"] == 1  # pool cache hit, no new retrieve() call

    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"}
    )
    assert feedback.status_code == 200
    # "More energy" changes the fingerprint, so this can't reuse the pool
    # cached under the old one either -- a genuinely new retrieval.
    assert calls["count"] == 2

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert row.prepared_next_json is None  # explicit invalidation, section 3.4

    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    # No stale prepared item was consumed (there wasn't one to consume) --
    # this fell through to _resolve_and_render same as the feedback call did,
    # which found the pool feedback just warmed under the new fingerprint
    # still fresh enough to reuse, so no *further* retrieve() call was needed.
    assert calls["count"] == 2


def test_calling_prepare_next_twice_in_a_row_does_not_duplicate_retrieval_work(client, monkeypatch):
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    first = client.post(f"/sessions/{session['id']}/prepare-next")
    assert first.status_code == 200
    assert first.json()["prepared"] is True
    assert calls["count"] == 2

    second = client.post(f"/sessions/{session['id']}/prepare-next")
    assert second.status_code == 200
    assert second.json()["prepared"] is True
    # Already-valid prepared item -- no second retrieval.
    assert calls["count"] == 2


def test_stop_session_clears_a_prepared_item(client, monkeypatch, db_session):
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    prep = client.post(f"/sessions/{session['id']}/prepare-next")
    assert prep.json()["prepared"] is True

    assert client.post(f"/sessions/{session['id']}/stop").status_code == 200

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert row.prepared_next_json is None


def test_prepare_next_discards_its_result_if_the_session_is_stopped_while_it_is_in_flight(
    client, monkeypatch, db_session
):
    # Simulates the race PHASE_C_PREFETCH_DESIGN.md section 3.5 describes:
    # stop_session() commits *while* prepare_next()'s own retrieval/render
    # work is still running, via a genuinely separate DB session (db_session,
    # distinct from the one the /prepare-next request itself uses) -- proving
    # prepare_next's pre-write re-check catches this, not just
    # advance_session's own re-validation at consume time (which only
    # protects against serving a stale item, not against writing one).
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]

    original_resolve = session_manager._resolve_and_render

    def resolve_then_stop_concurrently(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        concurrent_row = db_session.query(DJSession).filter_by(id=session_id).one()
        concurrent_row.status = "stopped"
        concurrent_row.prepared_next_json = None
        db_session.commit()
        return result

    monkeypatch.setattr(session_manager, "_resolve_and_render", resolve_then_stop_concurrently)

    response = client.post(f"/sessions/{session_id}/prepare-next")
    assert response.status_code == 200
    assert response.json()["prepared"] is False  # discarded, not resurrected

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    db_session.refresh(row)
    assert row.status == "stopped"
    assert row.prepared_next_json is None


def test_prepare_next_discards_its_result_if_intent_changes_while_it_is_in_flight(
    client, monkeypatch, db_session
):
    # Same race as above, but via a concurrent apply_feedback()-style intent
    # mutation (a different fingerprint) instead of a stop.
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]

    original_resolve = session_manager._resolve_and_render
    mutated_energy = {"value": None}

    def resolve_then_mutate_intent_concurrently(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        concurrent_row = db_session.query(DJSession).filter_by(id=session_id).one()
        mutated_intent = dict(concurrent_row.intent_json)
        mutated_intent["energy"] = "low" if mutated_intent["energy"] != "low" else "high"
        mutated_energy["value"] = mutated_intent["energy"]
        concurrent_row.intent_json = mutated_intent
        concurrent_row.prepared_next_json = None
        db_session.commit()
        return result

    monkeypatch.setattr(
        session_manager, "_resolve_and_render", resolve_then_mutate_intent_concurrently
    )

    response = client.post(f"/sessions/{session_id}/prepare-next")
    assert response.status_code == 200
    assert response.json()["prepared"] is False  # discarded, not resurrected

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    db_session.refresh(row)
    assert row.intent_json["energy"] == mutated_energy["value"]  # the concurrent mutation stuck
    assert row.prepared_next_json is None


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


def test_advance_leaves_session_unchanged_on_an_unanticipated_pipeline_error(client, monkeypatch):
    # "Zero interruptions" must hold even for a genuinely unexpected bug in
    # the pipeline (a DB error, a bad assumption, anything not already
    # anticipated as NoMatchingCandidate) -- advance must still return 200
    # with the session left exactly where it was, not a 500 that ends
    # playback client-side.
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated unexpected pipeline failure")

    monkeypatch.setattr("app.services.pipeline.segment_selector.LibrosaSegmentSelector.select", boom)
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
