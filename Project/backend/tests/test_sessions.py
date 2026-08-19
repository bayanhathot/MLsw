import time
from pathlib import Path

from conftest import register_and_login

from app.database.models.session import DJSession, UserPreference
from app.schemas import PromptIntent, SelectedSegment, Track
from app.services import session_candidate_pool, session_manager, upload_queue
from app.services.pipeline import audio_renderer
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


def _disable_reservation(monkeypatch):
    """Zeroes the live-crossfade reserved-tail window (session_manager.
    RESERVED_TRANSITION_MS) so advance() always does a real fresh
    resolution immediately, matching this test's pre-crossfade assumption
    -- it's exercising candidate rotation / prepared-item semantics, not
    the reservation mechanism itself. See the "live crossfades" tests
    further down for coverage of the reservation/bridge/reserved_plain
    mechanism this disables."""

    monkeypatch.setattr(session_manager, "RESERVED_TRANSITION_MS", 0)


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


def test_create_session_enriches_and_dispatches_analysis_for_a_new_audius_candidate(
    client, monkeypatch, db_session
):
    # Prompt 3 step 4's own requirement: verify this actually runs from a
    # real fresh-resolution call, not just from a direct unit test of
    # enrich_and_dispatch. create_session/apply_feedback/advance_session/
    # prepare_next all funnel through _resolve_and_render's one shared
    # call site (verified by reading the code, not assumed) -- this test
    # exercises that through the real HTTP path.
    from app.database.models.external_track import ExternalTrack
    from app.services.pipeline import external_track_cache

    monkeypatch.setattr(external_track_cache, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: [
            {
                "title": "Never Seen Before", "artist": "Someone New",
                "audio_url": "https://audio.example/unseen-1", "source_track_id": "unseen-1",
                "duration": 100, "source": "audius",
            },
        ],
    )
    monkeypatch.setattr("app.services.pipeline.audio_renderer._download", lambda url: (_DEMO_WAV_BYTES, None))
    dispatched = []
    monkeypatch.setattr(
        "app.services.upload_queue.upload_queue.submit_external_analysis",
        lambda track_id: dispatched.append(track_id),
    )

    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert session["nowPlaying"]["title"] == "Never Seen Before"

    row = db_session.query(ExternalTrack).filter_by(source="audius", external_id="unseen-1").first()
    assert row is not None
    assert row.analysis_status == "pending"
    assert dispatched == [row.id]


def test_create_session_gives_a_previously_analyzed_audius_track_real_segment_data(
    client, monkeypatch, db_session
):
    # Prompt 5 step 1, end to end: a *previously analyzed* Audius candidate
    # (external_tracks row already "completed") must feed real bpm/
    # musical_key/method through SegmentSelector into the session's own
    # pipeline trace, the same way an analyzed catalog track already does
    # -- not the whole-clip/no-data fallback an unanalyzed Audius track
    # still correctly gets (see test_external_track_downstream_parity.py
    # for the direct SegmentSelector/TransitionPlanner-level proof this
    # test corroborates through the real HTTP path).
    from app.database.models.external_track import ExternalTrack
    from app.services.pipeline import external_track_cache

    monkeypatch.setattr(external_track_cache, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    db_session.add(ExternalTrack(
        source="audius", external_id="already-analyzed-1", title="Known Track", artist="Known Artist",
        analysis_status="completed", analysis_version="v2",
        bpm=118.0, bpm_confidence=0.85, musical_key="G", key_mode="major", camelot="9B",
        key_confidence=0.7, integrated_loudness_lufs=-13.0,
        beat_grid_json=[0.5], downbeat_grid_json=[0.5], phrase_boundaries_json=[0.5],
        segment_start_second=5, segment_end_second=35, segment_method="chorus_detection",
    ))
    db_session.commit()
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: [
            {
                "title": "Known Track", "artist": "Known Artist",
                "audio_url": "https://audio.example/already-analyzed-1",
                "source_track_id": "already-analyzed-1", "duration": 100, "source": "audius",
            },
        ],
    )
    monkeypatch.setattr("app.services.pipeline.audio_renderer._download", lambda url: (_DEMO_WAV_BYTES, None))

    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert session["nowPlaying"]["title"] == "Known Track"

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    selector_trace = row.pipeline_trace_json["segment_selector"]
    assert selector_trace["method"] == "chorus_detection"
    assert selector_trace["bpm"] == 118.0
    assert selector_trace["musical_key"] == "G"


def test_create_session_rescues_a_render_with_the_catalog_when_every_audius_candidate_fails(
    client, monkeypatch, db_session
):
    # A systemically broken source (or a whole pool of unavailable tracks)
    # must not turn one resolution into an unbounded string of doomed
    # download attempts -- capped at AUDIO_RENDER_RETRY_LIMIT -- nor land the
    # session on a dead pass-through when a real fallback source (the local
    # catalog, never a remote fetch) can actually produce playable audio.
    # The catalog is sessions' primary retriever now: its own weak match
    # ("chill lofi beats" has no genre/artist to score, so it lands on the
    # generic "smooth" bucket) still defers to Audius first, which is what
    # actually serves the (unrenderable) candidates below -- so the render
    # rescue that lands back on the catalog is *not* a fallback, it's
    # primary reclaiming service after Audius's candidates turned out to be
    # dead.
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
    # False: the render rescue lands back on `retriever` (the catalog,
    # primary), not `fallback_retriever` -- see comment above.
    assert row.pipeline_trace_json["candidate_retriever"]["fell_back"] is False
    assert row.pipeline_trace_json["candidate_retriever"]["name"] == "catalog"


def test_create_session_keeps_the_pass_through_when_not_even_the_catalog_can_rescue_it(
    client, monkeypatch, db_session
):
    # The catalog rescue only helps when it actually has something to offer:
    # a named artist absent from the tiny local demo catalog still has
    # nowhere left to fall through to, so the session must land on the
    # retry-capped Audius attempt's honest pass-through, same as before the
    # rescue existed. The catalog (primary) has no Nancy Ajram at all, so
    # this genuinely falls through to Audius (fallback) at the retrieval
    # stage already, before rendering even starts.
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
    # True: the catalog (primary) had nothing at all for Nancy Ajram, so
    # Audius (fallback) served these candidates from the start.
    assert row.pipeline_trace_json["candidate_retriever"]["fell_back"] is True


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


def test_named_artist_absent_from_the_catalog_falls_back_to_audius(
    client, monkeypatch, db_session
):
    """The local catalog is sessions' primary retriever now (§12), but a
    named artist absent from the tiny local catalog still reaches Audius in
    the same resolution, via the fallback tier -- this is now a genuine
    fallback (fell_back is True), unlike when Audius itself was primary."""

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
    # section 8), so the fallback retriever's name is "audius_multi_query", not
    # the older single-query retriever's plain "audius".
    assert session.retriever_name == "audius_multi_query"
    assert session.pipeline_trace_json["candidate_retriever"]["name"] == "audius_multi_query"
    assert session.pipeline_trace_json["candidate_retriever"]["fell_back"] is True


def test_generic_vibe_prompt_with_a_weak_catalog_match_still_reaches_audius(
    client, monkeypatch, db_session
):
    """The bug a naive catalog-primary flip would reintroduce: a generic
    vibe/genre request (no named artist) matching only the catalog's coarse
    mood_bucket heuristic -- real signal only for the 4 curated seed rows,
    see catalog_retriever.is_strong_catalog_match -- must not be treated as
    a confident match that skips Audius entirely. Audius must still get a
    real look whenever the catalog's own top match isn't backed by a
    genre or artist signal."""

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
    assert session.pipeline_trace_json["candidate_retriever"]["fell_back"] is True


def test_when_audius_also_finds_nothing_the_catalogs_own_weak_match_still_serves(
    client, db_session
):
    """The other half of the same priority: Audius defaults to no results
    via the autouse fixture above. The catalog's own weak (mood_bucket-only)
    match for "hard gym workout" isn't strong enough to skip Audius, but
    once Audius also comes back empty, that weak-but-real catalog match is
    still preferred over an unrelated last-resort pick -- and since it's
    still the *primary* retriever's own result, fell_back reads False."""

    response = client.post("/sessions/start", json={"prompt": "hard gym workout"})
    assert response.status_code == 200
    body = response.json()
    assert body["vibeLabel"] == "Gym energy"

    session = db_session.query(DJSession).filter_by(id=body["id"]).one()
    assert session.retriever_name == "catalog"
    assert session.pipeline_trace_json["candidate_retriever"]["name"] == "catalog"
    assert session.pipeline_trace_json["candidate_retriever"]["fell_back"] is False


def test_advance_continues_without_input_and_rotates_through_candidates(client, monkeypatch):
    _patch_audius(monkeypatch, _wassouf_tracks())
    _disable_reservation(monkeypatch)
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
    _disable_reservation(monkeypatch)
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
    _disable_reservation(monkeypatch)
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
    _disable_reservation(monkeypatch)
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
    # Reservation deliberately left on here (unlike most of this file's
    # other prepared-item tests): prepare-next only ever prepares a
    # *bridge* out of a real reserved tail, so proving "an expired bridge
    # is rejected" needs that tail to actually exist.
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
    prepared_bridge_url = prep.json()["audioUrl"]

    time.sleep(0.1)
    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    # The expired bridge was rejected, not served -- but the current
    # segment's own already-rendered reserved tail still plays out in full
    # before any new retrieval happens (never fabricated, never skipped).
    assert response.json()["audioUrl"] != prepared_bridge_url
    assert calls["count"] == 2

    # *Now* nothing further is staged (the reserved tail was the last
    # already-rendered piece) -- the next advance is a genuine fresh
    # resolution, restoring this test's original "eventually falls through
    # to a real resolution" guarantee.
    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
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
    _disable_reservation(monkeypatch)
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


def test_advance_rejects_a_prepared_item_already_played_by_a_concurrent_advance(
    client, monkeypatch, db_session
):
    # The race the containment check exists for: prepare_next()'s render
    # alone can take 25s+ (AUDIO_RENDER_TIME_BUDGET_SECONDS), well past the
    # ~10s of track remaining that triggers it client-side, so the current
    # track can genuinely end and get advanced past *before* prepare_next()
    # writes its own result -- and because selection is fully deterministic
    # (same intent, same exclude set), that result is often the very same
    # track advance_session already committed. Simulated here via a
    # genuinely separate DB session (db_session) that commits the "advance
    # already played this track" state right after prepare_next's own
    # resolution finishes, but before it re-checks and writes.
    # Reservation deliberately left on (unlike most of this file's other
    # prepared-item tests): prepare-next only ever prepares a *bridge* out
    # of a real reserved tail, so this race needs that tail to actually
    # exist.
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]

    original_resolve = session_manager._resolve_and_render

    def resolve_then_advance_concurrently(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        track = result[0]
        concurrent_row = db_session.query(DJSession).filter_by(id=session_id).one()
        concurrent_row.played_track_keys_json = (
            concurrent_row.played_track_keys_json or []
        ) + [session_manager._track_key(track)]
        db_session.commit()
        return result

    monkeypatch.setattr(session_manager, "_resolve_and_render", resolve_then_advance_concurrently)

    prep = client.post(f"/sessions/{session_id}/prepare-next")
    assert prep.status_code == 200
    # Status/fingerprint are unchanged by the race, so the write itself is
    # not discarded -- it's a *valid*, but now already-played, prepared item.
    assert prep.json()["prepared"] is True

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    db_session.refresh(row)
    prepared_track_key = row.prepared_next_json["track_key"]
    prepared_audio_url = row.prepared_next_json["now_playing"]["audio_url"]
    prepared_title = row.prepared_next_json["now_playing"]["title"]
    assert prepared_track_key in row.played_track_keys_json  # confirms the race landed

    monkeypatch.setattr(session_manager, "_resolve_and_render", original_resolve)
    calls = _count_retrieve_calls(monkeypatch)
    response = client.post(f"/sessions/{session_id}/advance")
    assert response.status_code == 200
    body = response.json()
    # Not the stale prepared item -- the rejected bridge was discarded, and
    # the current segment's own already-rendered reserved tail played out
    # in full instead (never fabricated, never skipped), with no retrieval.
    assert body["audioUrl"] != prepared_audio_url
    assert body["nowPlaying"]["title"] != prepared_title
    assert calls["count"] == 0

    # *Now* nothing further is staged -- the next advance is a genuine
    # fresh resolution, restoring this test's original "a real re-resolution
    # served something else" guarantee.
    response = client.post(f"/sessions/{session_id}/advance")
    assert response.status_code == 200
    body = response.json()
    assert body["audioUrl"] != prepared_audio_url
    assert body["nowPlaying"]["title"] != prepared_title
    # A genuine resolution, not a same-track fast path that happened to
    # look different -- the fast path makes zero retrieve() calls.
    assert calls["count"] == 1


def test_smoother_feedback_invalidates_an_already_prepared_item(client, monkeypatch, db_session):
    # "smoother" leaves intent.energy/vocals (and so the retrieval
    # fingerprint) unchanged while still replacing now_playing -- unlike
    # "more energy"/"less vocals", advance_session's fingerprint check alone
    # would NOT catch a stale prepared item here; only apply_feedback's
    # now-unconditional prepared_next_json clear does.
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]

    prep = client.post(f"/sessions/{session_id}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    db_session.refresh(row)
    prepared_audio_url = row.prepared_next_json["now_playing"]["audio_url"]

    feedback = client.post(
        f"/sessions/{session_id}/feedback", json={"feedback": "Smoother transitions please"}
    )
    assert feedback.status_code == 200

    db_session.refresh(row)
    assert row.prepared_next_json is None  # invalidated despite the unchanged fingerprint

    response = client.post(f"/sessions/{session_id}/advance")
    assert response.status_code == 200
    # A real resolution ran instead of replaying the now-stale prepared item
    # (planned against a previous_segment that isn't playing anymore).
    assert response.json()["audioUrl"] != prepared_audio_url


def test_advance_never_serves_a_prepared_item_whose_track_key_was_already_played(
    client, monkeypatch, db_session
):
    # A direct, non-concurrency reproduction of the containment rule itself:
    # a prepared item with an otherwise-valid (matching fingerprint,
    # unexpired) record is still rejected once its track_key is already in
    # played_track_keys_json, regardless of how it got there.
    _patch_audius(monkeypatch, _wassouf_tracks())
    # This test is about the containment check itself, not the reserved-tail
    # mechanism (see _disable_reservation's docstring).
    _disable_reservation(monkeypatch)
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    assert calls["count"] == 1

    row = db_session.query(DJSession).filter_by(id=session["id"]).one()
    already_played = row.played_track_keys_json[0]
    played_before = list(row.played_track_keys_json)
    intent = PromptIntent.model_validate(row.intent_json)
    fingerprint = session_candidate_pool.fingerprint_for(intent)
    row.prepared_next_json = {
        "track_key": already_played,
        "artist": "George Wassouf",
        "now_playing": {"audio_url": "https://stale.example/should-not-be-served.wav"},
        "reasoning": {},
        "pipeline_trace": {},
        "fingerprint": session_manager._fingerprint_as_json(fingerprint),
        "prepared_at": time.monotonic(),
    }
    db_session.commit()

    response = client.post(f"/sessions/{session['id']}/advance")
    assert response.status_code == 200
    assert response.json()["audioUrl"] != "https://stale.example/should-not-be-served.wav"
    assert calls["count"] == 2  # a real resolution ran, not the fast path

    db_session.refresh(row)
    # Exactly one new entry was appended by the real resolution -- the
    # already-played track_key from the rejected prepared item was not
    # appended a second time.
    assert row.played_track_keys_json.count(already_played) == 1
    assert len(row.played_track_keys_json) == len(played_before) + 1


def test_prepare_next_deletes_the_rendered_file_when_its_result_is_discarded(
    client, monkeypatch, db_session
):
    # Same race as
    # test_prepare_next_discards_its_result_if_the_session_is_stopped_while_it_is_in_flight,
    # but asserting the on-disk render AudioRenderer already wrote is deleted
    # too, not left as a permanent orphan once the DB write is (correctly)
    # skipped.
    _patch_audius(monkeypatch, _wassouf_tracks())
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]

    original_resolve = session_manager._resolve_and_render
    rendered_audio_url = {"value": None}

    def resolve_then_stop_concurrently(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        rendered_audio_url["value"] = result[2]["audio_url"]  # now_playing
        concurrent_row = db_session.query(DJSession).filter_by(id=session_id).one()
        concurrent_row.status = "stopped"
        concurrent_row.prepared_next_json = None
        db_session.commit()
        return result

    monkeypatch.setattr(session_manager, "_resolve_and_render", resolve_then_stop_concurrently)

    response = client.post(f"/sessions/{session_id}/prepare-next")
    assert response.status_code == 200
    assert response.json()["prepared"] is False  # discarded, not resurrected

    # Sanity precondition: this really was a rendered file, not a
    # pass-through with nothing on disk to begin with.
    assert f"/{audio_renderer.RENDER_SUBDIR}/" in rendered_audio_url["value"]
    filename = rendered_audio_url["value"].rsplit("/", 1)[-1]
    rendered_path = upload_queue.UPLOAD_DIR / audio_renderer.RENDER_SUBDIR / filename
    assert not rendered_path.exists()


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


def test_feedback_self_heals_from_the_catalogs_own_weak_match_to_audius(client, monkeypatch, db_session):
    """Requirement: self-healing re-resolution still works under the local
    catalog's new primary role. A session that started on the catalog's own
    weak (mood_bucket-only) match -- Audius had nothing then -- must pick
    Audius back up once Audius starts returning results, via the fallback
    tier: each fresh resolution tries the catalog anew, and a weak catalog
    match always still gives Audius a real look, nothing is pinned to how
    the session started.

    Deliberately starts on the "focus" bucket (energy="low", via the
    "focus" keyword), not "energy" (which "hard gym workout" would trigger
    via "gym"/"workout" -- but those exact words *also* set
    intent.energy="high" directly in the deterministic parser, so a "more
    energy" feedback mutation there is a same-value no-op and never
    actually changes the session_candidate_pool fingerprint; apply_feedback
    passes no exclude_track_keys of its own, so nothing about that call
    forces a cache miss on exhaustion either -- self-healing here only
    happens via a genuine fingerprint change, and low->high is one)."""

    session = client.post("/sessions/start", json={"prompt": "a focus session"}).json()
    # Served by the catalog's own weak match (Audius defaults to no results
    # via the autouse fixture above).
    assert session["vibeLabel"] == "Deep work focus"

    _patch_audius(monkeypatch, _wassouf_tracks())
    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "More energy"}
    )
    assert feedback.status_code == 200
    assert feedback.json()["nowPlaying"]["artist"] == "George Wassouf"

    healed = db_session.query(DJSession).filter_by(id=session["id"]).one()
    assert healed.retriever_name == "audius_multi_query"
    assert healed.pipeline_trace_json["candidate_retriever"]["fell_back"] is True


def test_reasoning_and_next_direction_reflect_feedback_history(client):
    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    assert "Give feedback" in session["reasoning"]["nextDirection"]
    assert session["reasoning"]["selectedMoment"]
    assert session["reasoning"]["transitionPlan"]

    feedback = client.post(
        f"/sessions/{session['id']}/feedback", json={"feedback": "Smoother please"}
    ).json()
    assert "Smoother please" in feedback["reasoning"]["nextDirection"]


# --- §8 follow-up: deadline-aware retry loop --------------------------------
# (Prompt 16's own batch measurement found the render-retry budget was only
# ever checked *between* candidate attempts, never *before* starting one --
# see session_manager._MAX_SINGLE_ATTEMPT_SECONDS.)


def _slow_candidates(count):
    return [
        Track(
            source="audius", source_track_id=f"slow-{index}", title=f"Slow {index}", artist="Artist",
            album=None, audio_url=f"https://audio.example/slow-{index}", cover_url=None,
            duration_seconds=180, genre=None, vibe=None, vibe_label=None, tags=None,
            catalog_track_id=None, local_path=None,
        )
        for index in range(count)
    ]


def test_try_render_ranked_candidates_stops_early_once_remaining_budget_cant_fit_another_attempt(
    monkeypatch, db_session
):
    # Several candidates in a row are slow (now individually bounded --
    # see audio_renderer._bounded) -- the retry loop must stop *starting*
    # new attempts once the shared deadline can't plausibly fit another
    # one, rather than trying every candidate regardless.
    from app.schemas import StagedRender, StagedTrackRender
    from app.services.pipeline.dependencies import get_segment_selector, get_transition_planner

    monkeypatch.setattr(session_manager, "_MAX_SINGLE_ATTEMPT_SECONDS", 0.2)

    class _SlowFailingRenderer:
        def __init__(self, delay_seconds):
            self.delay_seconds = delay_seconds
            self.calls = 0

        def render_track_transition(self, segment, *, resume_offset_ms, reserved_ms):
            self.calls += 1
            time.sleep(self.delay_seconds)
            return StagedTrackRender(
                body=StagedRender(
                    audio_url=segment.track.audio_url, duration_ms=1000,
                    is_pass_through=True, fallback_reason="simulated_slow_failure",
                ),
            )

    renderer = _SlowFailingRenderer(delay_seconds=0.15)
    deadline = time.monotonic() + 0.3  # only room for ~2 attempts at 0.15s each

    track, segment, transition, rendered, skipped, timings = session_manager._try_render_ranked_candidates(
        db_session, _slow_candidates(6), get_segment_selector(), get_transition_planner(), renderer,
        previous_segment=None, prefers_smoother=False, deadline=deadline,
    )

    assert renderer.calls < 6  # did not try every candidate
    assert any(entry["fallback_reason"] == "insufficient_time_remaining" for entry in skipped)


def test_try_render_ranked_candidates_always_tries_at_least_the_first_candidate(monkeypatch, db_session):
    # Even if the deadline has *already* passed before this function is
    # even called, it must still try once -- it has to return something.
    from app.schemas import StagedRender, StagedTrackRender
    from app.services.pipeline.dependencies import get_segment_selector, get_transition_planner

    monkeypatch.setattr(session_manager, "_MAX_SINGLE_ATTEMPT_SECONDS", 999)  # never "enough" remaining

    class _InstantRenderer:
        def render_track_transition(self, segment, *, resume_offset_ms, reserved_ms):
            return StagedTrackRender(
                body=StagedRender(
                    audio_url=segment.track.audio_url, duration_ms=1000, is_pass_through=False,
                ),
            )

    already_expired_deadline = time.monotonic() - 10
    track, segment, transition, rendered, skipped, timings = session_manager._try_render_ranked_candidates(
        db_session, _slow_candidates(1), get_segment_selector(), get_transition_planner(),
        _InstantRenderer(), previous_segment=None, prefers_smoother=False,
        deadline=already_expired_deadline,
    )
    assert track.source_track_id == "slow-0"


# --- Phase 9: live in-session crossfades (reserved-region mechanism) ------


def test_reserved_ms_for_floors_to_half_a_short_segments_duration():
    stub_track = Track(
        source="audius", source_track_id="1", title="T", artist="A", album=None,
        audio_url="https://example.test/1", cover_url=None, duration_seconds=90,
        genre=None, vibe=None, vibe_label=None, catalog_track_id=None, local_path=None,
    )
    short_segment = SelectedSegment(
        track=stub_track, start_second=0, end_second=6,
        method="whole_clip", bpm=None, musical_key=None,
    )
    # Half of 6000ms, well under RESERVED_TRANSITION_MS -- the short segment
    # itself is the binding constraint, not the constant.
    assert session_manager._reserved_ms_for(short_segment) == 3000

    long_segment = SelectedSegment(
        track=stub_track, start_second=0, end_second=60,
        method="whole_clip", bpm=None, musical_key=None,
    )
    assert session_manager._reserved_ms_for(long_segment) == session_manager.RESERVED_TRANSITION_MS


def test_session_body_then_bridge_then_continuation_covers_the_full_sequence_with_no_gap_or_duplication(
    client, monkeypatch, db_session
):
    # The full three-stage sequence a live session actually goes through:
    # body (with a reserved tail already rendered) -> a prepared bridge
    # promoted in -> the bridge's own stashed next-body promoted in, with
    # no further retrieval at any promotion step.
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]
    assert calls["count"] == 1

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    body_now_playing = row.now_playing_json
    assert body_now_playing["stage"] == "body"
    assert body_now_playing["resume_offset_ms"] == 0
    segment = body_now_playing["segment"]
    full_duration_ms = (segment["end_second"] - segment["start_second"]) * 1000
    # The reservation actually wired through session_manager matches
    # _reserved_ms_for's own contract applied to the real resolved segment.
    assert body_now_playing["reserved_ms"] == min(
        session_manager.RESERVED_TRANSITION_MS, full_duration_ms // 2
    )
    assert body_now_playing["reserved_ms"] > 0  # sanity: this fixture reserves something real
    assert body_now_playing["tail_audio_url"] is not None

    prep = client.post(f"/sessions/{session_id}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True
    assert calls["count"] == 2  # prepare-next's own one real resolution

    db_session.refresh(row)
    prepared_bridge = row.prepared_next_json["now_playing"]
    assert prepared_bridge["stage"] == "bridge"
    # The bridge's actually-used crossfade never exceeds what this segment
    # actually reserved -- the physical ceiling from TransitionPlanner's
    # max_crossfade_ms.
    assert prepared_bridge["resume_offset_ms"] <= body_now_playing["reserved_ms"]

    advanced_to_bridge = client.post(f"/sessions/{session_id}/advance")
    assert advanced_to_bridge.status_code == 200
    assert advanced_to_bridge.json()["audioUrl"] == prepared_bridge["audio_url"]
    assert calls["count"] == 2  # promoting the ready bridge made no new retrieve() call

    db_session.refresh(row)
    bridge_now_playing = row.now_playing_json
    assert bridge_now_playing["stage"] == "bridge"
    stashed_resume_offset_ms = bridge_now_playing["resume_offset_ms"]
    stashed_next_body_url = bridge_now_playing["next_body_audio_url"]
    assert row.prepared_next_json is None  # consumed and cleared

    advanced_to_body = client.post(f"/sessions/{session_id}/advance")
    assert advanced_to_body.status_code == 200
    # Pure promotion of the already-staged next body -- no further retrieval.
    assert calls["count"] == 2
    assert advanced_to_body.json()["audioUrl"] == stashed_next_body_url

    db_session.refresh(row)
    continuation_now_playing = row.now_playing_json
    assert continuation_now_playing["stage"] == "body"
    assert continuation_now_playing["resume_offset_ms"] == stashed_resume_offset_ms
    assert continuation_now_playing["audio_url"] == stashed_next_body_url


def test_session_bridge_crossfade_is_capped_at_the_reserved_tail_length(
    client, monkeypatch, db_session
):
    _patch_audius(monkeypatch, _wassouf_tracks())
    # Shorter than MIN_CROSSFADE_MS (1500ms) -- DeterministicTransitionPlanner's
    # own tempo/key logic would never pick this on its own; only the
    # reservation's physical ceiling can force it this low.
    monkeypatch.setattr(session_manager, "RESERVED_TRANSITION_MS", 800)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    reserved_ms = row.now_playing_json["reserved_ms"]
    assert reserved_ms == 800  # the fixture segment is long enough not to hit the half-duration floor

    prep = client.post(f"/sessions/{session_id}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True

    db_session.refresh(row)
    bridge_now_playing = row.prepared_next_json["now_playing"]
    assert bridge_now_playing["resume_offset_ms"] <= reserved_ms


def test_session_reserved_tail_plays_in_full_when_no_bridge_is_ready_yet(
    client, monkeypatch, db_session
):
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]
    assert calls["count"] == 1

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    assert row.prepared_next_json is None  # nothing prepared yet
    tail_audio_url = row.now_playing_json["tail_audio_url"]

    # No /prepare-next call -- advance() must still serve the reserved tail
    # in full rather than skip or fabricate anything, before a fresh
    # resolution ever happens.
    response = client.post(f"/sessions/{session_id}/advance")
    assert response.status_code == 200
    assert response.json()["audioUrl"] == tail_audio_url
    assert calls["count"] == 1  # no retrieval at all for this step

    db_session.refresh(row)
    assert row.now_playing_json["stage"] == "reserved_plain"

    # And *now* the next advance does a genuine fresh resolution.
    response = client.post(f"/sessions/{session_id}/advance")
    assert response.status_code == 200
    assert calls["count"] == 2


def test_prepare_next_bridge_failure_falls_through_to_the_next_candidate_and_leaves_current_track_untouched(
    client, monkeypatch, db_session
):
    tracks = _wassouf_tracks()
    monkeypatch.setattr(
        "app.services.pipeline.audius_retriever.search_tracks",
        lambda prompt, limit=5: tracks,
    )

    def selective_download(url):
        # Only the top-ranked *next*-track candidate is broken -- proves
        # the bridge path reuses the same per-candidate retry loop
        # render_track_transition already relies on, rather than giving up
        # on the first failure.
        if url == tracks[0]["audio_url"]:
            return None, "download_failed_ConnectError"
        return _DEMO_WAV_BYTES, None

    monkeypatch.setattr("app.services.pipeline.audio_renderer._download", selective_download)

    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]
    row = db_session.query(DJSession).filter_by(id=session_id).one()
    original_now_playing = dict(row.now_playing_json)

    prep = client.post(f"/sessions/{session_id}/prepare-next")
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True

    db_session.refresh(row)
    # The current track's own already-rendered body/tail were never
    # touched -- prepare_next only ever writes to prepared_next_json.
    assert row.now_playing_json == original_now_playing
    assert row.prepared_next_json["now_playing"]["stage"] == "bridge"


def test_advance_still_works_on_a_legacy_session_row_with_no_stage_key(
    client, monkeypatch, db_session
):
    # A session row created before the live-crossfade "stage" key existed:
    # now_playing_json had none of stage/resume_offset_ms/reserved_ms/
    # tail_audio_url at all. advance_session must still fall straight
    # through to a real resolution, exactly like its only behavior before
    # this mechanism existed.
    _patch_audius(monkeypatch, _wassouf_tracks())
    calls = _count_retrieve_calls(monkeypatch)
    session = client.post(
        "/sessions/start", json={"prompt": "play something by George Wassouf"}
    ).json()
    session_id = session["id"]
    assert calls["count"] == 1

    row = db_session.query(DJSession).filter_by(id=session_id).one()
    legacy_now_playing = {
        key: value for key, value in row.now_playing_json.items()
        if key not in ("stage", "resume_offset_ms", "reserved_ms", "tail_audio_url")
    }
    row.now_playing_json = legacy_now_playing
    db_session.commit()

    response = client.post(f"/sessions/{session_id}/advance")
    assert response.status_code == 200
    assert calls["count"] == 2
