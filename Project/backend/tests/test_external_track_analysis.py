"""Prompt 2: the shared analyze_audio() DSP core, and its second adapter,
analyze_external_track() -- temporary-fetch, analyze, persist, delete,
with cleanup guaranteed on both success and induced failure."""

from pathlib import Path

import pytest

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.services import audio_analysis
from app.services.pipeline import audio_renderer

_DEMO_WAV_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"


def _external_row(db_session, **overrides) -> ExternalTrack:
    fields = {
        "source": "audius",
        "external_id": "demo-track-1",
        "title": "T",
        "artist": "A",
        "analysis_status": "pending",
    }
    fields.update(overrides)
    row = ExternalTrack(**fields)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_analyze_audio_matches_analyze_catalog_track_against_the_same_file(db_session, tmp_path):
    # Same fixture file through both entry points -- analyze_audio() run
    # directly, and analyze_catalog_track() (which now calls analyze_audio()
    # internally) run against a CatalogTrack pointed at a copy of the same
    # bytes (placed under the test's own UPLOAD_DIR/catalog, exactly where
    # analyze_catalog_track expects it -- see catalog_retriever.CATALOG_AUDIO_SUBDIR).
    # Bit-identical results proves the refactor changed nothing about
    # catalog-track behavior, per Prompt 2 step 1's explicit requirement.
    direct = audio_analysis.analyze_audio(str(_DEMO_WAV_PATH), label="direct")

    catalog_dir = audio_analysis.upload_queue.UPLOAD_DIR / audio_analysis.CATALOG_AUDIO_SUBDIR
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "demo-copy.wav").write_bytes(_DEMO_WAV_PATH.read_bytes())

    row = CatalogTrack(
        title="T", artist="A", storage_name="demo-copy.wav", content_type="audio/wav",
        analysis_status="pending",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    audio_analysis.analyze_catalog_track(row.id)

    db_session.refresh(row)
    assert row.analysis_status == "completed"
    assert row.bpm == direct.bpm
    assert row.bpm_confidence == direct.bpm_confidence
    assert row.musical_key == direct.musical_key
    assert row.key_mode == direct.key_mode
    assert row.camelot == direct.camelot
    assert row.key_confidence == direct.key_confidence
    assert row.beat_grid_json == direct.beat_grid
    assert row.segment_start_second == direct.segment_start_second
    assert row.segment_end_second == direct.segment_end_second
    assert row.segment_method == direct.segment_method


def _spy_mkstemp(monkeypatch, captured: list[str]):
    import tempfile as tempfile_module

    real_mkstemp = tempfile_module.mkstemp

    def spy(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        captured.append(path)
        return fd, path

    monkeypatch.setattr(audio_analysis.tempfile, "mkstemp", spy)


def test_analyze_external_track_persists_analysis_and_deletes_temp_file(db_session, monkeypatch):
    demo_bytes = _DEMO_WAV_PATH.read_bytes()
    monkeypatch.setattr(audio_renderer, "_download", lambda url: (demo_bytes, None))
    captured_paths: list[str] = []
    _spy_mkstemp(monkeypatch, captured_paths)

    row = _external_row(db_session)
    audio_analysis.analyze_external_track(row.id)

    db_session.refresh(row)
    assert row.analysis_status == "completed"
    assert row.analysis_version == audio_analysis.ANALYSIS_VERSION
    assert row.analyzed_at is not None
    assert row.analysis_attempt_count == 1
    assert row.is_stale is False
    assert row.bpm is not None
    assert row.musical_key is not None
    import hashlib
    assert row.audio_sha256 == hashlib.sha256(demo_bytes).hexdigest()

    assert len(captured_paths) == 1
    assert not Path(captured_paths[0]).exists()  # temp file cleaned up on success


def test_analyze_external_track_cleans_up_temp_file_on_analysis_failure(db_session, monkeypatch):
    # Not real audio -- analyze_audio() will raise once librosa tries to
    # decode it, exercising the failure branch of the try/finally.
    monkeypatch.setattr(audio_renderer, "_download", lambda url: (b"not real audio bytes", None))
    captured_paths: list[str] = []
    _spy_mkstemp(monkeypatch, captured_paths)

    row = _external_row(db_session)
    audio_analysis.analyze_external_track(row.id)

    db_session.refresh(row)
    assert row.analysis_status == "failed"
    assert row.analysis_attempt_count == 1
    assert row.analysis_last_failed_at is not None
    assert len(captured_paths) == 1
    assert not Path(captured_paths[0]).exists()  # cleaned up even on failure


def test_analyze_external_track_download_failure_marks_failed_with_no_temp_file(db_session, monkeypatch):
    monkeypatch.setattr(audio_renderer, "_download", lambda url: (None, "download_failed_ConnectError"))
    captured_paths: list[str] = []
    _spy_mkstemp(monkeypatch, captured_paths)

    row = _external_row(db_session)
    audio_analysis.analyze_external_track(row.id)

    db_session.refresh(row)
    assert row.analysis_status == "failed"
    assert row.analysis_attempt_count == 1
    assert captured_paths == []  # never even got to writing a temp file


def test_analyze_external_track_unsupported_source_marks_failed(db_session):
    row = _external_row(db_session, source="some_other_provider")
    audio_analysis.analyze_external_track(row.id)

    db_session.refresh(row)
    assert row.analysis_status == "failed"
    assert row.analysis_attempt_count == 1


def test_analyze_external_track_missing_row_is_a_no_op():
    audio_analysis.analyze_external_track(999999)  # must not raise
