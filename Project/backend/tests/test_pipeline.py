"""Unit coverage for the pipeline stages that HTTP-level tests only exercise
indirectly: fuzzy artist matching, segment selection, and transition
planning."""

import pytest

from app.database.models.catalog import CatalogTrack
from app.schemas import PromptIntent, SelectedSegment, Track, TransitionPlan
from app.services.pipeline import audius_retriever
from app.services.pipeline.audio_renderer import PydubAudioRenderer
from app.services.pipeline.audius_retriever import (
    MIN_POOL_SIZE,
    MultiQueryAudiusRetriever,
    _rank_by_metadata,
    _reciprocal_rank_fusion,
)
from app.services.pipeline.catalog_retriever import (
    ARTIST_MATCH_THRESHOLD,
    CatalogTrackRetriever,
    _trigram_similarity,
)
from app.services.pipeline.dependencies import _build_vibe_understander
from app.services.pipeline.query_planner import build_queries
from app.services.pipeline.segment_selector import LibrosaSegmentSelector
from app.services.pipeline.transition_planner import DeterministicTransitionPlanner
from app.services.pipeline.vibe import DeterministicOnlyVibeUnderstander, OllamaVibeUnderstander
from app.services.prompt_parser import deterministic_parse


def _intent(**overrides) -> PromptIntent:
    base = dict(mood="balanced", energy="medium", vocals="neutral", genres=[], search_query="x")
    base.update(overrides)
    return PromptIntent(**base)


def test_trigram_similarity_is_symmetric_and_bounded():
    a, b = "zzzqx nonexistent artist ptrxk", "zonix ai dj"
    assert _trigram_similarity(a, b) == _trigram_similarity(b, a)
    assert _trigram_similarity("drake", "drake") == 1.0
    assert _trigram_similarity("drake", "drakee") > ARTIST_MATCH_THRESHOLD
    assert _trigram_similarity("drake", "zonix ai dj") < ARTIST_MATCH_THRESHOLD


def test_catalog_retriever_named_artist_below_threshold_returns_nothing(db_session):
    retriever = CatalogTrackRetriever()
    tracks = retriever.retrieve(db_session, _intent(artist="Completely Unrelated Name"), limit=5)
    assert tracks == []


def test_catalog_retriever_mood_bucket_matches_seeded_rows(db_session):
    retriever = CatalogTrackRetriever()
    tracks = retriever.retrieve(db_session, _intent(energy="high"), limit=5)
    assert tracks and tracks[0].vibe == "energy"
    assert tracks[0].vibe_label == "Gym energy"


def test_catalog_retriever_finds_close_but_imperfect_artist_spelling(db_session):
    retriever = CatalogTrackRetriever()
    # A near-miss (missing a letter) of the seeded "Zonix AI DJ" artist.
    tracks = retriever.retrieve(db_session, _intent(artist="Zonix AI D"), limit=5)
    assert tracks
    assert tracks[0].artist == "Zonix AI DJ"


def test_deterministic_artist_extraction_handles_common_phrasings():
    assert deterministic_parse("chill vibes by Nova Blackwood").artist == "Nova Blackwood"
    assert deterministic_parse("something similar to Drake but chill").artist == "Drake"
    assert deterministic_parse("high energy workout").artist is None


# --- query_planner.build_queries -------------------------------------------


def test_build_queries_puts_artist_first():
    intent = _intent(artist="Drake", genres=["hip-hop", "pop"], mood="chill", search_query="chill vibes")
    queries = build_queries(intent)
    assert queries[0] == "Drake"


def test_build_queries_includes_combined_pair_for_multiple_genres():
    intent = _intent(genres=["lofi", "jazz"], search_query="something")
    queries = build_queries(intent)
    assert "lofi" in queries
    assert "jazz" in queries
    assert "lofi jazz" in queries


def test_build_queries_keeps_raw_search_query_as_last_resort():
    intent = _intent(artist="Drake", genres=["lofi"], mood="chill", search_query="raw sentence")
    queries = build_queries(intent, max_queries=10)
    assert queries[-1] == "raw sentence"


def test_build_queries_respects_max_queries_cap():
    intent = _intent(artist="Drake", genres=["lofi", "jazz", "rock"], mood="chill", search_query="raw sentence")
    queries = build_queries(intent, max_queries=2)
    assert len(queries) == 2
    assert queries[0] == "Drake"


def test_build_queries_dedupes_case_insensitive_duplicates():
    # A duplicate can arise from any two signals collapsing to the same
    # string (e.g. an artist name that happens to equal a genre); build_queries
    # must keep only the first occurrence rather than searching it twice.
    intent = _intent(artist="Techno", genres=["techno", "house"], search_query="Techno")
    queries = build_queries(intent, max_queries=10)
    lowered = [query.lower() for query in queries]
    assert lowered.count("techno") == 1


def test_build_queries_skips_degenerate_mood_genre_combo_when_they_match():
    # Regression test: mood="lofi" with genres=["lofi"] used to produce a
    # "lofi lofi" query (the mood+genre combo doesn't dedupe against a bare
    # "lofi" already added, since they're different strings) -- a redundant
    # search with no retrieval value over "lofi" alone. The combo must be
    # skipped whenever mood already equals the genre it would be paired with.
    intent = _intent(genres=["lofi"], mood="lofi", search_query="lofi")
    queries = build_queries(intent, max_queries=10)
    assert queries == ["lofi"]
    assert "lofi lofi" not in queries

    # Sanity: a genuinely different mood still produces the combo query.
    distinct_mood_intent = _intent(genres=["lofi"], mood="chill", search_query="raw")
    distinct_mood_queries = build_queries(distinct_mood_intent, max_queries=10)
    assert "chill lofi" in distinct_mood_queries


# --- audius_retriever._reciprocal_rank_fusion -------------------------------


def test_rrf_ranks_a_track_found_in_multiple_lists_above_one_found_once():
    fused = _reciprocal_rank_fusion([["a", "b", "c"], ["c", "d"]])
    assert fused[0] == "c"


def test_rrf_empty_input_returns_empty_output():
    assert _reciprocal_rank_fusion([]) == []


def test_rrf_single_list_preserves_its_order():
    assert _reciprocal_rank_fusion([["x", "y", "z"]]) == ["x", "y", "z"]


# --- audius_retriever._rank_by_metadata -------------------------------------


def test_rank_by_metadata_prefers_genre_match_over_a_slightly_better_raw_rank():
    intent = _intent(genres=["lofi"], mood="balanced", energy="medium")
    pool = {
        "better_rank_no_genre": _track(source_track_id="1", genre="rock"),
        "worse_rank_genre_match": _track(source_track_id="2", genre="lofi"),
    }
    # Filler keys absent from `pool` spread the two real candidates across
    # adjacent positions in a long fused order, so their raw RRF-derived
    # retrieval scores are close (unlike a bare 2-item list, where position
    # alone would swamp every other signal) and the genre weight decides.
    filler = [f"filler-{i}" for i in range(8)]
    fused_order = filler[:4] + ["better_rank_no_genre", "worse_rank_genre_match"] + filler[4:]
    ranked = _rank_by_metadata(pool, fused_order, intent)
    assert ranked[0] == "worse_rank_genre_match"


# --- MultiQueryAudiusRetriever, end-to-end (no real network calls) ---------


def test_multi_query_retriever_dedupes_across_queries_and_respects_limit(db_session, monkeypatch):
    def fake_search_tracks(query, limit=5):
        if query.lower() == "lofi":
            return [
                {"title": "Lofi A", "artist": "Artist A", "audio_url": "https://a", "source_track_id": "lofi-a", "duration": 100, "genre": "lofi"},
                {"title": "Shared", "artist": "Artist S", "audio_url": "https://s", "source_track_id": "shared-1", "duration": 100, "genre": "lofi"},
            ]
        if query.lower() == "chill lofi":
            return [
                {"title": "Shared", "artist": "Artist S", "audio_url": "https://s", "source_track_id": "shared-1", "duration": 100, "genre": "lofi"},
                {"title": "Lofi B", "artist": "Artist B", "audio_url": "https://b", "source_track_id": "lofi-b", "duration": 100, "genre": "lofi"},
            ]
        return []

    monkeypatch.setattr(audius_retriever, "search_tracks", fake_search_tracks)
    intent = _intent(genres=["lofi"], mood="chill", search_query="something else entirely")
    retriever = MultiQueryAudiusRetriever()
    results = retriever.retrieve(db_session, intent, limit=2)

    assert len(results) == 2
    ids = [track.source_track_id for track in results]
    assert len(ids) == len(set(ids))  # deduped -- "shared-1" was returned by two queries


def test_multi_query_retriever_returns_empty_list_when_audius_finds_nothing(db_session, monkeypatch):
    monkeypatch.setattr(audius_retriever, "search_tracks", lambda query, limit=5: [])
    intent = _intent(genres=["techno"], search_query="anything")
    retriever = MultiQueryAudiusRetriever()
    assert retriever.retrieve(db_session, intent, limit=5) == []


def test_relaxation_ladder_stops_once_min_pool_size_is_reached(db_session, monkeypatch):
    call_log: list[str] = []

    def broad_tracks():
        return [
            {
                "title": f"Broad {i}",
                "artist": "Artist",
                "audio_url": f"https://audio.example/broad-{i}",
                "source_track_id": f"broad-{i}",
                "duration": 100,
            }
            for i in range(MIN_POOL_SIZE)
        ]

    def fake_search_tracks(query, limit=5):
        call_log.append(query)
        # Only the 4th query (the two-genre combined query, reached in round
        # 2) returns anything -- the first two queries (round 1, the most
        # specific) come back empty, forcing the ladder to broaden.
        if query == "lofi jazz":
            return broad_tracks()
        return []

    monkeypatch.setattr(audius_retriever, "search_tracks", fake_search_tracks)
    intent = _intent(genres=["lofi", "jazz", "rock"], mood="chill", search_query="raw sentence")
    retriever = MultiQueryAudiusRetriever()
    results = retriever.retrieve(db_session, intent, limit=MIN_POOL_SIZE)

    assert len(results) == MIN_POOL_SIZE
    # Stops calling as soon as the pool hits MIN_POOL_SIZE at the end of
    # round 2 ("rock", "lofi jazz") -- round 3's "chill lofi" is never tried.
    assert call_log == ["lofi", "jazz", "rock", "lofi jazz"]


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
        catalog_track_id=None,
        local_path=None,
    )
    base.update(overrides)
    return Track(**base)


def test_segment_selector_uses_whole_clip_for_tracks_without_completed_analysis(db_session):
    selector = LibrosaSegmentSelector()
    segment = selector.select(db_session, _track())
    assert segment.method == "whole_clip"
    assert segment.start_second == 0
    assert segment.end_second == 90


def test_segment_selector_reads_cached_analysis_for_completed_catalog_tracks(db_session):
    row = CatalogTrack(
        title="Analyzed", artist="Someone", storage_name="x.wav", content_type="audio/wav",
        duration_seconds=120, analysis_status="completed", bpm=128.0, musical_key="A",
        segment_start_second=30, segment_end_second=60, segment_method="chorus_detection",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    selector = LibrosaSegmentSelector()
    track = _track(source="catalog", catalog_track_id=row.id, duration_seconds=120)
    segment = selector.select(db_session, track)
    assert segment.method == "chorus_detection"
    assert (segment.start_second, segment.end_second) == (30, 60)
    assert segment.bpm == 128.0
    assert segment.musical_key == "A"


def _segment(bpm=None, key=None) -> SelectedSegment:
    return SelectedSegment(
        track=_track(), start_second=0, end_second=30, method="whole_clip", bpm=bpm, musical_key=key
    )


def test_transition_planner_first_segment_has_no_transition_unless_smoother_requested():
    planner = DeterministicTransitionPlanner()
    plain = planner.plan(None, _segment())
    assert plain.crossfade_ms == 0
    assert plain.style == "cut"

    smoother = planner.plan(None, _segment(), prefers_smoother=True)
    assert smoother.crossfade_ms > 0
    assert smoother.style == "crossfade"


def test_transition_planner_rewards_compatible_tempo_and_key():
    planner = DeterministicTransitionPlanner()
    compatible = planner.plan(_segment(bpm=120, key="C"), _segment(bpm=121, key="C"))
    clashing = planner.plan(_segment(bpm=90, key="C"), _segment(bpm=140, key="F#"))
    assert compatible.crossfade_ms > clashing.crossfade_ms


def test_transition_planner_smoother_flag_always_lengthens_crossfade():
    planner = DeterministicTransitionPlanner()
    previous, next_segment = _segment(bpm=90, key="C"), _segment(bpm=140, key="F#")
    normal = planner.plan(previous, next_segment)
    smoother = planner.plan(previous, next_segment, prefers_smoother=True)
    assert smoother.crossfade_ms > normal.crossfade_ms


def test_rendered_session_audio_is_actually_servable(client):
    session = client.post("/sessions/start", json={"prompt": "chill lofi beats"}).json()
    served = client.get(session["audioUrl"].removeprefix("/api"))
    assert served.status_code == 200
    assert served.content[:4] == b"RIFF"


def test_media_route_404s_for_an_unknown_render(client):
    assert client.get("/media/renders/does-not-exist.wav").status_code == 404


def test_audio_renderer_degrades_to_pass_through_when_a_track_cannot_be_fetched(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.audio_renderer._download", lambda url: None
    )
    renderer = PydubAudioRenderer()
    segment = _segment()
    rendered = renderer.render([segment], [])
    assert rendered.is_pass_through is True
    assert rendered.audio_url == segment.track.audio_url

    other = _segment()
    plan = TransitionPlan(crossfade_ms=3000, style="crossfade", notes="x")
    composite = renderer.render([segment, other], [plan])
    assert composite.is_pass_through is True
    assert len(composite.offsets) == 2


def test_vibe_provider_defaults_to_ollama_and_degrades_without_config(monkeypatch):
    # A missing/incomplete Ollama config must not crash the app:
    # OllamaVibeUnderstander already falls back to the deterministic parse on
    # every call in that case (parse_prompt), the same as Audius being
    # unavailable -- only a warning is logged, mirroring how a missing
    # GROQ_API_KEY used to be handled before Groq was removed.
    monkeypatch.delenv("VIBE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert isinstance(_build_vibe_understander(), OllamaVibeUnderstander)

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.invalid")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    assert isinstance(_build_vibe_understander(), OllamaVibeUnderstander)


def test_vibe_provider_can_be_switched_to_ollama_or_none(monkeypatch):
    monkeypatch.setenv("VIBE_LLM_PROVIDER", "ollama")
    assert isinstance(_build_vibe_understander(), OllamaVibeUnderstander)

    monkeypatch.setenv("VIBE_LLM_PROVIDER", "none")
    assert isinstance(_build_vibe_understander(), DeterministicOnlyVibeUnderstander)

    monkeypatch.setenv("VIBE_LLM_PROVIDER", "NONE")
    assert isinstance(_build_vibe_understander(), DeterministicOnlyVibeUnderstander)


def test_vibe_provider_rejects_an_unknown_value(monkeypatch):
    monkeypatch.setenv("VIBE_LLM_PROVIDER", "spotify-llm")
    with pytest.raises(RuntimeError, match="VIBE_LLM_PROVIDER"):
        _build_vibe_understander()


def test_vibe_provider_rejects_groq_as_no_longer_valid(monkeypatch):
    monkeypatch.setenv("VIBE_LLM_PROVIDER", "groq")
    with pytest.raises(RuntimeError, match="VIBE_LLM_PROVIDER"):
        _build_vibe_understander()
