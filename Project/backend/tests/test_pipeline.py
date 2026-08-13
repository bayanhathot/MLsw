"""Unit coverage for the pipeline stages that HTTP-level tests only exercise
indirectly: fuzzy artist matching, segment selection, and transition
planning."""

from app.database.models.catalog import CatalogTrack
from app.schemas import PromptIntent, SelectedSegment, Track, TransitionPlan
from app.services.pipeline.audio_renderer import PydubAudioRenderer
from app.services.pipeline.catalog_retriever import (
    ARTIST_MATCH_THRESHOLD,
    CatalogTrackRetriever,
    _trigram_similarity,
)
from app.services.pipeline.segment_selector import LibrosaSegmentSelector
from app.services.pipeline.transition_planner import DeterministicTransitionPlanner
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
