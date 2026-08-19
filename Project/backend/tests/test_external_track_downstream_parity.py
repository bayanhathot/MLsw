"""Prompt 5: confirm an enriched (previously-analyzed) Audius Track behaves
identically to a catalog Track from SegmentSelector downward, confirm it
never becomes catalog-retrievable just by being cached, and confirm the
explicit retrieval-time-ranking scope boundary (see audius_retriever.
_score_candidates' own docstring) holds."""

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.schemas import PromptIntent, Track
from app.services.pipeline.catalog_retriever import CatalogTrackRetriever
from app.services.pipeline.segment_selector import LibrosaSegmentSelector
from app.services.pipeline.transition_planner import DeterministicTransitionPlanner

_HIGH_KEY_CONFIDENCE = 0.9


def _audius_track(**overrides) -> Track:
    base = dict(
        source="audius", source_track_id="ext-1", title="T", artist="A", album=None,
        audio_url="https://example.test/1", cover_url=None, duration_seconds=90,
        genre=None, vibe=None, vibe_label=None, tags=None, catalog_track_id=None,
        local_path=None,
    )
    base.update(overrides)
    return Track(**base)


def _shared_analysis_fields(**overrides) -> dict:
    fields = dict(
        analysis_status="completed",
        bpm=120.0, bpm_confidence=0.9,
        musical_key="C", key_mode="major", camelot="8B", key_confidence=_HIGH_KEY_CONFIDENCE,
        integrated_loudness_lufs=-14.0,
        beat_grid_json=[0.5, 1.0, 1.5, 2.0], downbeat_grid_json=[0.5], phrase_boundaries_json=[0.5],
        segment_start_second=10, segment_end_second=40, segment_method="chorus_detection",
    )
    fields.update(overrides)
    return fields


def test_segment_selector_treats_a_completed_external_track_identically_to_a_catalog_track(db_session):
    catalog_row = CatalogTrack(
        title="T", artist="A", storage_name="x.wav", content_type="audio/wav",
        **_shared_analysis_fields(),
    )
    external_row = ExternalTrack(source="audius", external_id="ext-1", title="T", artist="A", **_shared_analysis_fields())
    db_session.add_all([catalog_row, external_row])
    db_session.commit()
    db_session.refresh(catalog_row)
    db_session.refresh(external_row)

    catalog_track = Track(
        source="catalog", source_track_id=str(catalog_row.id), title="T", artist="A",
        album=None, audio_url="/media/x.wav", cover_url=None, duration_seconds=90,
        genre=None, vibe=None, vibe_label=None, tags=None,
        catalog_track_id=catalog_row.id, local_path=None,
    )
    external_track = _audius_track(external_track_id=external_row.id)

    selector = LibrosaSegmentSelector()
    catalog_segment = selector.select(db_session, catalog_track)
    external_segment = selector.select(db_session, external_track)

    for field in (
        "start_second", "end_second", "method", "bpm", "bpm_confidence", "musical_key",
        "key_mode", "camelot", "key_confidence", "phrase_boundaries", "integrated_loudness_lufs",
    ):
        assert getattr(catalog_segment, field) == getattr(external_segment, field), field


def test_unanalyzed_external_track_still_degrades_to_whole_clip(db_session):
    row = ExternalTrack(source="audius", external_id="pending-1", title="T", artist="A", analysis_status="pending")
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    segment = LibrosaSegmentSelector().select(
        db_session, _audius_track(source_track_id="pending-1", external_track_id=row.id, duration_seconds=77)
    )
    assert segment.method == "whole_clip"
    assert segment.bpm is None
    assert segment.start_second == 0
    assert segment.end_second == 77


def test_stale_external_track_is_not_trusted_even_though_completed(db_session):
    row = ExternalTrack(
        source="audius", external_id="stale-1", title="T", artist="A", is_stale=True,
        **_shared_analysis_fields(),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    segment = LibrosaSegmentSelector().select(
        db_session, _audius_track(source_track_id="stale-1", external_track_id=row.id, duration_seconds=77)
    )
    assert segment.method == "whole_clip"
    assert segment.bpm is None


def test_transition_planner_produces_real_harmonic_and_phrase_planning_for_an_enriched_external_track(db_session):
    # The previous segment is an ordinary hand-built SelectedSegment (same
    # key/high confidence, a phrase boundary within reach) -- the next
    # segment comes from the REAL SegmentSelector reading a real
    # ExternalTrack row, proving the actual enrichment path (not just a
    # hand-built SelectedSegment) feeds TransitionPlanner real data.
    from app.schemas import SelectedSegment

    previous = SelectedSegment(
        track=_audius_track(source_track_id="prev"), start_second=0, end_second=30,
        method="whole_clip", bpm=120.0, bpm_confidence=0.9,
        musical_key="C", key_mode="major", camelot="8B", key_confidence=_HIGH_KEY_CONFIDENCE,
        phrase_boundaries=[4.0, 12.0, 20.0, 28.0],  # 28.0 is within reach of end_second=30
    )

    row = ExternalTrack(
        source="audius", external_id="enriched-1", title="T", artist="A",
        **_shared_analysis_fields(bpm=121.0, segment_start_second=0, segment_end_second=30),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    next_segment = LibrosaSegmentSelector().select(
        db_session, _audius_track(source_track_id="enriched-1", external_track_id=row.id)
    )
    assert next_segment.method == "chorus_detection"  # real data, not whole-clip fallback

    plan = DeterministicTransitionPlanner().plan(previous, next_segment, max_crossfade_ms=4000)

    # Real harmonic (same key -> same_key bonus) and phrase-aware planning
    # engaged -- not the degraded bpm-only behavior an unanalyzed Audius
    # track would get (which would still crossfade, but without any of
    # this reasoning, and "no data" showing up in transition.notes).
    assert plan.style == "crossfade"
    assert plan.crossfade_ms > 0
    assert "key" in plan.notes.lower() or "phrase" in plan.notes.lower()


def test_catalog_track_retriever_never_surfaces_an_externally_cached_audius_track(db_session):
    # A distinctive artist name that exists ONLY in external_tracks --
    # if CatalogTrackRetriever ever accidentally queried/joined against
    # that table, this artist would show up in its results.
    external_only_artist = "Only In External Tracks Zzyx"
    db_session.add(ExternalTrack(
        source="audius", external_id="leak-check-1", title="Leaky Track",
        artist=external_only_artist, analysis_status="completed",
    ))
    db_session.add(CatalogTrack(
        title="Real Catalog Track", artist="A Real Catalog Artist",
        storage_name="x.wav", content_type="audio/wav", analysis_status="not_applicable",
        visibility="public",
    ))
    db_session.commit()

    intent = PromptIntent(
        mood="balanced", energy="medium", vocals="neutral", genres=[],
        artist=external_only_artist, artist_mode="required", search_query=external_only_artist,
    )
    results = CatalogTrackRetriever().retrieve(db_session, intent, limit=10)
    assert all(track.artist != external_only_artist for track in results)
    assert all(track.source == "catalog" for track in results)
