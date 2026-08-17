"""Unit coverage for the pipeline stages that HTTP-level tests only exercise
indirectly: fuzzy artist matching, segment selection, and transition
planning."""

import os
import time
from pathlib import Path

import pytest

from app.core.security import hash_password
from app.database.models.catalog import CatalogTrack
from app.database.models.user import User
from app.schemas import PromptIntent, SelectedSegment, Track, TransitionPlan
from app.services.pipeline import audio_renderer, audius_retriever
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
    a, b = "zzzqx nonexistent artist ptrxk", "cuemix ai dj"
    assert _trigram_similarity(a, b) == _trigram_similarity(b, a)
    assert _trigram_similarity("drake", "drake") == 1.0
    assert _trigram_similarity("drake", "drakee") > ARTIST_MATCH_THRESHOLD
    assert _trigram_similarity("drake", "cuemix ai dj") < ARTIST_MATCH_THRESHOLD


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
    # A near-miss (missing a letter) of the seeded "Cuemix AI DJ" artist.
    tracks = retriever.retrieve(db_session, _intent(artist="Cuemix AI D"), limit=5)
    assert tracks
    assert tracks[0].artist == "Cuemix AI DJ"


def _make_user(db_session, username):
    user = User(username=username, email=f"{username}@example.com", hashed_password=hash_password("s3cret!!"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_catalog_retriever_excludes_a_private_track_from_a_guest_session(db_session):
    owner = _make_user(db_session, "owner_private")
    db_session.add(
        CatalogTrack(
            owner_id=owner.id, title="Owner Only", artist="Zzq Unique Private Artist",
            visibility="private", storage_name="x.wav", content_type="audio/wav",
        )
    )
    db_session.commit()
    retriever = CatalogTrackRetriever()
    tracks = retriever.retrieve(
        db_session, _intent(artist="Zzq Unique Private Artist"), limit=5, viewer_id=None
    )
    assert tracks == []


def test_catalog_retriever_excludes_a_private_track_from_another_users_session(db_session):
    owner = _make_user(db_session, "owner_private2")
    other = _make_user(db_session, "other_viewer")
    db_session.add(
        CatalogTrack(
            owner_id=owner.id, title="Owner Only", artist="Zzq Second Private Artist",
            visibility="private", storage_name="x.wav", content_type="audio/wav",
        )
    )
    db_session.commit()
    retriever = CatalogTrackRetriever()
    tracks = retriever.retrieve(
        db_session, _intent(artist="Zzq Second Private Artist"), limit=5, viewer_id=other.id
    )
    assert tracks == []


def test_catalog_retriever_includes_a_private_track_for_its_own_owner(db_session):
    owner = _make_user(db_session, "owner_private3")
    db_session.add(
        CatalogTrack(
            owner_id=owner.id, title="Owner Only", artist="Zzq Third Private Artist",
            visibility="private", storage_name="x.wav", content_type="audio/wav",
        )
    )
    db_session.commit()
    retriever = CatalogTrackRetriever()
    tracks = retriever.retrieve(
        db_session, _intent(artist="Zzq Third Private Artist"), limit=5, viewer_id=owner.id
    )
    assert len(tracks) == 1
    assert tracks[0].title == "Owner Only"


def test_catalog_retriever_includes_a_public_track_for_a_guest_session(db_session):
    owner = _make_user(db_session, "owner_public")
    db_session.add(
        CatalogTrack(
            owner_id=owner.id, title="Shared Track", artist="Zzq Public Artist",
            visibility="public", storage_name="x.wav", content_type="audio/wav",
        )
    )
    db_session.commit()
    retriever = CatalogTrackRetriever()
    tracks = retriever.retrieve(
        db_session, _intent(artist="Zzq Public Artist"), limit=5, viewer_id=None
    )
    assert len(tracks) == 1
    assert tracks[0].title == "Shared Track"


def test_deterministic_artist_extraction_handles_common_phrasings():
    assert deterministic_parse("chill vibes by Nova Blackwood").artist == "Nova Blackwood"
    assert deterministic_parse("something similar to Drake but chill").artist == "Drake"
    assert deterministic_parse("high energy workout").artist is None


def test_deterministic_artist_extraction_captures_artist_mode():
    cases = [
        ("play some George Wassouf music", "George Wassouf", "required"),
        ("play George Wassouf", "George Wassouf", "required"),
        ("music by George Wassouf", "George Wassouf", "required"),
        ("something like George Wassouf", "George Wassouf", "reference"),
        ("similar to George Wassouf", "George Wassouf", "reference"),
        ("emotional Arabic music", None, "none"),
        # Own additions, generalizing the required pattern beyond the exact
        # phrasings above -- "put on X" / "give me some X" / "music from X".
        ("put on Fairuz", "Fairuz", "required"),
        ("give me some Adele", "Adele", "required"),
        ("music from Coldplay", "Coldplay", "required"),
    ]
    for prompt, expected_artist, expected_mode in cases:
        intent = deterministic_parse(prompt)
        assert intent.artist == expected_artist, prompt
        assert intent.artist_mode == expected_mode, prompt


def test_bare_play_trigger_does_not_hijack_a_vibe_description():
    # The generic bare "play X" trigger (added for "play george wassouf",
    # which had no matching pattern at all before) must not swallow a
    # vibe-only prompt that also happens to start with "play" -- a real
    # artist name isn't usually made up entirely of the same genre/mood/
    # energy words deterministic_parse already reads from the raw prompt.
    for prompt in (
        "play something chill and relaxing",
        "play chill lofi beats for coding",
    ):
        intent = deterministic_parse(prompt)
        assert intent.artist is None, prompt
        assert intent.artist_mode == "none", prompt


def test_play_prefixed_reference_trigger_is_not_swallowed_as_a_required_artist():
    # Regression test: the bare "play X" trigger greedily captures anything
    # after "play ", including a reference trigger phrase that immediately
    # follows it ("play something like Drake" -> candidate="something like
    # Drake") -- that must be re-extracted as a reference match (just the
    # artist name), not treated as a required-mode artist literally named
    # "something like Drake".
    cases = [
        ("play something like George Wassouf", "George Wassouf", "reference"),
        ("play similar to George Wassouf", "George Wassouf", "reference"),
        ("play reminds me of George Wassouf", "George Wassouf", "reference"),
    ]
    for prompt, expected_artist, expected_mode in cases:
        intent = deterministic_parse(prompt)
        assert intent.artist == expected_artist, prompt
        assert intent.artist_mode == expected_mode, prompt


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


def test_build_queries_uses_energy_as_fallback_when_no_genre_is_found():
    # Regression test: a prompt like "gym energy" that the deterministic
    # parser correctly maps to energy="high" but finds no genre word for
    # (genres=[], mood stays "balanced") used to fall straight through to
    # searching Audius with the raw sentence -- exactly the case that
    # returns zero hits. energy is always populated (unlike mood/genres),
    # so it is used as a cleaner fallback query before the raw sentence.
    intent = _intent(genres=[], mood="balanced", energy="high", search_query="gym energy")
    queries = build_queries(intent, max_queries=10)
    assert queries == ["high energy", "gym energy"]

    # "low" energy maps to "chill".
    low_energy_intent = _intent(genres=[], mood="balanced", energy="low", search_query="something calm")
    assert "chill" in build_queries(low_energy_intent, max_queries=10)

    # "medium" has no term -- falls straight through to the raw sentence.
    medium_energy_intent = _intent(genres=[], mood="balanced", energy="medium", search_query="a balanced mix")
    assert build_queries(medium_energy_intent, max_queries=10) == ["a balanced mix"]

    # Sanity: when a genre IS found, the energy fallback never fires -- the
    # genre query is already better than a generic energy term.
    with_genre_intent = _intent(genres=["techno"], mood="balanced", energy="high", search_query="techno set")
    assert "high energy" not in build_queries(with_genre_intent, max_queries=10)


def test_build_queries_required_artist_is_not_diluted_by_genre_in_the_first_round():
    # Regression test for artist_mode: a required-artist request ("play
    # george wassouf") must not share its first retrieval round
    # (queries[0:2], see _relaxation_rounds in audius_retriever.py) with an
    # unrelated genre query. The raw search_query is promoted ahead of
    # genre/mood queries instead -- it's still artist-relevant (the artist
    # name is literally in it) -- while the genre remains available later
    # as a secondary option rather than being dropped.
    intent = _intent(
        artist="George Wassouf",
        artist_mode="required",
        genres=["techno"],
        search_query="play some techno by george wassouf",
    )
    queries = build_queries(intent, max_queries=10)
    assert queries[0] == "George Wassouf"
    assert queries[1] == "play some techno by george wassouf"
    assert "techno" in queries[2:]

    # Sanity: the same artist under a non-required mode is not reordered --
    # normal genre-before-search_query priority still applies.
    reference_intent = _intent(
        artist="George Wassouf",
        artist_mode="reference",
        genres=["techno"],
        search_query="something like george wassouf but techno",
    )
    reference_queries = build_queries(reference_intent, max_queries=10)
    assert reference_queries[-1] == "something like george wassouf but techno"


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
    ranked, _breakdown = _rank_by_metadata(pool, fused_order, intent)
    assert ranked[0] == "worse_rank_genre_match"


def test_rank_by_metadata_does_not_bottom_rank_a_candidate_with_no_metadata_at_all():
    # A candidate with no genre/mood/tags at all (just a real Audius title
    # and stream URL) must not be artificially penalized by missing
    # sub-scores counting as 0 -- if its RRF retrieval confidence is strong,
    # its total should reflect that alone, not get dragged down by signals
    # it simply has no data for.
    intent = _intent(genres=["lofi"], mood="chill", energy="high")
    pool = {
        "no_metadata_top_rank": _track(source_track_id="1", genre=None, vibe=None, tags=None),
        "full_metadata_bottom_rank": _track(source_track_id="2", genre="rock", vibe="Angry", tags="metal,rock"),
    }
    # no_metadata_top_rank is far ahead in the fused order (strong retrieval
    # confidence); full_metadata_bottom_rank is far behind, and its metadata
    # doesn't match the intent at all either.
    fused_order = ["no_metadata_top_rank"] + [f"filler-{i}" for i in range(8)] + ["full_metadata_bottom_rank"]
    ranked, breakdown = _rank_by_metadata(pool, fused_order, intent)

    assert ranked[0] == "no_metadata_top_rank"
    # The only available signal for it is retrieval -- its total must equal
    # that signal exactly (a weighted average of one item is that item),
    # not something lower because absent signals were folded in as zeros.
    assert breakdown["no_metadata_top_rank"]["total"] == breakdown["no_metadata_top_rank"]["retrieval"]
    assert breakdown["no_metadata_top_rank"]["genre"] is None
    assert breakdown["no_metadata_top_rank"]["mood"] is None
    assert breakdown["no_metadata_top_rank"]["tag"] is None


def test_rank_by_metadata_required_artist_match_outranks_a_better_rrf_rank():
    intent = _intent(artist="George Wassouf", artist_mode="required")
    pool = {
        "better_rank_wrong_artist": _track(source_track_id="1", artist="Someone Else Entirely"),
        "worse_rank_matching_artist": _track(source_track_id="2", artist="George Wassouf"),
    }
    fused_order = ["better_rank_wrong_artist"] + [f"filler-{i}" for i in range(8)] + ["worse_rank_matching_artist"]
    ranked, breakdown = _rank_by_metadata(pool, fused_order, intent)

    assert ranked[0] == "worse_rank_matching_artist"
    assert breakdown["worse_rank_matching_artist"]["artist_match"] == 1.0
    assert breakdown["better_rank_wrong_artist"]["artist_match"] < 1.0


def test_rank_by_metadata_scores_always_stay_within_0_and_1():
    intent = _intent(
        genres=["lofi", "jazz"], mood="chill", energy="high",
        artist="George Wassouf", artist_mode="required",
    )
    pool = {
        "a": _track(source_track_id="1", genre="lofi", vibe="Peaceful", tags="chill,lofi,study", artist="George Wassouf"),
        "b": _track(source_track_id="2", genre="rock", vibe="Angry", tags="metal", artist="Totally Different"),
        "c": _track(source_track_id="3", genre=None, vibe=None, tags=None, artist="Nobody In Particular"),
    }
    fused_order = list(pool.keys())
    _ranked, breakdown = _rank_by_metadata(pool, fused_order, intent, recent_artists=frozenset({"Totally Different"}))
    for key, scores in breakdown.items():
        for name, value in scores.items():
            if value is not None:
                assert 0.0 <= value <= 1.0, (key, name, value)


# --- audius_retriever._score_candidates: session-aware artist diversity ----


def test_rank_by_metadata_penalizes_a_candidate_whose_artist_was_played_recently():
    intent = _intent(genres=["lofi"], mood="balanced", energy="medium")
    pool = {
        "better_rank_repeat_artist": _track(source_track_id="1", genre="lofi", artist="Artist A"),
        "worse_rank_fresh_artist": _track(source_track_id="2", genre="lofi", artist="Artist B"),
    }
    # Same filler-spreading trick as the genre-match test above: without it,
    # a 2-item fused order gives one candidate a 1.0 retrieval_score and the
    # other 0.0, a gap too large for any other signal to overcome -- filler
    # keeps their raw retrieval confidence close so the diversity weight
    # actually decides.
    filler = [f"filler-{i}" for i in range(8)]
    fused_order = filler[:4] + ["better_rank_repeat_artist", "worse_rank_fresh_artist"] + filler[4:]
    ranked, breakdown = _rank_by_metadata(
        pool, fused_order, intent, recent_artists=frozenset({"Artist A"})
    )

    assert ranked[0] == "worse_rank_fresh_artist"
    assert breakdown["better_rank_repeat_artist"]["diversity"] == 0.0
    assert breakdown["worse_rank_fresh_artist"]["diversity"] == 1.0


def test_rank_by_metadata_required_artist_is_exempt_from_diversity_penalty():
    # A required-artist request ("play george wassouf" again) must never be
    # penalized for repeating that exact artist -- that's the whole point of
    # asking for it by name. The diversity signal is excluded entirely for
    # that candidate (None), not just scored favorably despite the repeat.
    intent = _intent(artist="George Wassouf", artist_mode="required")
    pool = {
        "matching_artist_played_recently": _track(source_track_id="1", artist="George Wassouf"),
        "different_artist_not_recent": _track(source_track_id="2", artist="Someone Else"),
    }
    fused_order = ["matching_artist_played_recently", "different_artist_not_recent"]
    ranked, breakdown = _rank_by_metadata(
        pool, fused_order, intent, recent_artists=frozenset({"George Wassouf"})
    )

    assert breakdown["matching_artist_played_recently"]["diversity"] is None
    assert ranked[0] == "matching_artist_played_recently"


def test_diversity_penalty_is_flat_not_graduated_by_recency():
    # Design choice, not an oversight: CandidateRetriever.retrieve's
    # interface passes recent_artists as an unordered frozenset[str], which
    # carries no information about *when* within the session each artist
    # last played. A graduated penalty (smaller for "recently but not
    # immediately previous") would need an ordered structure instead --
    # since the interface mandates a frozenset, the penalty here is flat:
    # any artist in recent_artists at all gets the same penalty, regardless
    # of position.
    intent = _intent(genres=["lofi"], mood="balanced", energy="medium")
    pool = {
        "a": _track(source_track_id="1", genre="lofi", artist="Artist A"),
        "b": _track(source_track_id="2", genre="lofi", artist="Artist B"),
    }
    fused_order = ["a", "b"]
    _ranked, breakdown = _rank_by_metadata(
        pool, fused_order, intent, recent_artists=frozenset({"Artist A", "Artist B"})
    )
    assert breakdown["a"]["diversity"] == breakdown["b"]["diversity"] == 0.0


def test_multi_query_retriever_applies_recent_artists_penalty_end_to_end(db_session, monkeypatch):
    def fake_search_tracks(query, limit=5):
        items = [
            {
                "title": f"Filler {i}",
                "artist": "Filler Artist",
                "audio_url": f"https://audio.example/filler-{i}",
                "source_track_id": f"filler-{i}",
                "duration": 100,
                "genre": "lofi",
            }
            for i in range(8)
        ]
        items[3] = {
            "title": "Repeat Track", "artist": "Repeat Artist",
            "audio_url": "https://audio.example/repeat", "source_track_id": "repeat-1",
            "duration": 100, "genre": "lofi",
        }
        items[4] = {
            "title": "Fresh Track", "artist": "Fresh Artist",
            "audio_url": "https://audio.example/fresh", "source_track_id": "fresh-1",
            "duration": 100, "genre": "lofi",
        }
        return items

    monkeypatch.setattr(audius_retriever, "search_tracks", fake_search_tracks)
    intent = _intent(genres=["lofi"], search_query="lofi")
    retriever = MultiQueryAudiusRetriever()
    results = retriever.retrieve(
        db_session, intent, limit=8, recent_artists=frozenset({"Repeat Artist"})
    )

    artists = [track.artist for track in results]
    assert artists.index("Fresh Artist") < artists.index("Repeat Artist")


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


def test_multi_query_retriever_returns_more_than_five_candidates_for_a_normal_vibe_prompt(db_session, monkeypatch):
    # Regression test for the raised CANDIDATES_PER_QUERY/MIN_POOL_SIZE
    # defaults: a normal vibe prompt with room in `limit` should surface a
    # real pool of alternatives, not just enough to fill the old default of
    # 5 -- session_manager's exclude-scan needs headroom over
    # _PLAYED_TRACK_HISTORY to have fresh tracks left to fall through to.
    def fake_search_tracks(query, limit=5):
        return [
            {
                "title": f"{query} track {i}",
                "artist": "Artist",
                "audio_url": f"https://audio.example/{query}-{i}",
                "source_track_id": f"{query}-{i}",
                "duration": 100,
                "genre": "lofi",
            }
            for i in range(limit)
        ]

    monkeypatch.setattr(audius_retriever, "search_tracks", fake_search_tracks)
    intent = _intent(genres=["lofi"], mood="chill", search_query="chill lofi beats for coding")
    retriever = MultiQueryAudiusRetriever()
    results = retriever.retrieve(db_session, intent, limit=15)

    assert len(results) > 5


def test_multi_query_retriever_returns_empty_list_when_audius_finds_nothing(db_session, monkeypatch):
    monkeypatch.setattr(audius_retriever, "search_tracks", lambda query, limit=5: [])
    intent = _intent(genres=["techno"], search_query="anything")
    retriever = MultiQueryAudiusRetriever()
    assert retriever.retrieve(db_session, intent, limit=5) == []


def test_multi_query_retriever_round_still_issues_and_fuses_every_querys_own_results(
    db_session, monkeypatch
):
    # A round's queries are now fired concurrently (ThreadPoolExecutor), not
    # one after another -- this confirms that didn't silently drop a query,
    # duplicate a call, or cross-wire one query's results into another's
    # ranked list: each of the round's two queries returns one distinctly-
    # ID'd track, and both must survive into the final fused/ranked pool.
    calls = []

    def fake_search_tracks(query, limit=5):
        calls.append(query)
        if query == "lofi":
            return [{
                "title": "Lofi Track", "artist": "Artist A", "audio_url": "https://a",
                "source_track_id": "lofi-only", "duration": 100, "genre": "lofi",
            }]
        if query == "chill lofi":
            return [{
                "title": "Chill Track", "artist": "Artist B", "audio_url": "https://b",
                "source_track_id": "chill-only", "duration": 100, "genre": "lofi",
            }]
        return []

    monkeypatch.setattr(audius_retriever, "search_tracks", fake_search_tracks)
    # genres=["lofi"] + mood="chill" builds exactly the 2-query round
    # ["lofi", "chill lofi"] (build_queries dedupes the raw search_query
    # against the mood+genre combo it equals), so this is exactly one round.
    intent = _intent(genres=["lofi"], mood="chill", search_query="chill lofi")
    retriever = MultiQueryAudiusRetriever()
    results = retriever.retrieve(db_session, intent, limit=10)

    # Both queries were actually issued -- exactly once each, unchanged from
    # sequential behavior -- just not necessarily in list order.
    assert sorted(calls) == ["chill lofi", "lofi"]
    ids = {track.source_track_id for track in results}
    assert {"lofi-only", "chill-only"} <= ids


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
    # Order within a round is no longer guaranteed (queries in a round run
    # concurrently, see MultiQueryAudiusRetriever.retrieve), so this checks
    # which queries ran, not the sequence -- round-to-round ordering is still
    # deterministic (rounds themselves stay sequential), which "chill lofi"
    # never appearing at all already confirms.
    assert set(call_log) == {"lofi", "jazz", "rock", "lofi jazz"}
    assert "chill lofi" not in call_log


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
        "app.services.pipeline.audio_renderer._download",
        lambda url: (None, "download_failed_ConnectError"),
    )
    renderer = PydubAudioRenderer()
    segment = _segment()
    rendered = renderer.render([segment], [])
    assert rendered.is_pass_through is True
    assert rendered.audio_url == segment.track.audio_url
    # Surfaced in the pipeline debug trace so a pass-through is diagnosable
    # without grepping backend logs (session_manager._resolve_and_render).
    assert rendered.fallback_reason == "download_failed_ConnectError"

    other = _segment()
    plan = TransitionPlan(crossfade_ms=3000, style="crossfade", notes="x")
    composite = renderer.render([segment, other], [plan])
    assert composite.is_pass_through is True
    assert len(composite.offsets) == 2
    assert composite.fallback_reason == "download_failed_ConnectError"


_DEMO_WAV_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"


def _local_file_segment() -> SelectedSegment:
    # local_path set (a real WAV, read natively by pydub) so _load_clip
    # succeeds without a network call, and _export() actually runs --
    # the pass-through path above never reaches _export() at all.
    return SelectedSegment(
        track=_track(local_path=str(_DEMO_WAV_PATH)),
        start_second=0,
        end_second=1,
        method="whole_clip",
        bpm=None,
        musical_key=None,
    )


def test_export_sweeps_a_render_older_than_the_ttl():
    directory = audio_renderer._render_dir()
    stale_path = directory / "stale.wav"
    stale_path.write_bytes(b"stale placeholder bytes")
    old_mtime = time.time() - audio_renderer.RENDERED_AUDIO_TTL_SECONDS - 60
    os.utime(stale_path, (old_mtime, old_mtime))

    rendered = PydubAudioRenderer().render([_local_file_segment()], [])

    assert rendered.is_pass_through is False  # sanity: _export() really ran
    assert not stale_path.exists()


def test_export_leaves_a_fresh_render_alone():
    directory = audio_renderer._render_dir()
    fresh_path = directory / "fresh.wav"
    fresh_path.write_bytes(b"fresh placeholder bytes")

    rendered = PydubAudioRenderer().render([_local_file_segment()], [])

    assert rendered.is_pass_through is False
    assert rendered.fallback_reason is None
    assert fresh_path.exists()


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
