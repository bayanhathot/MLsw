"""Targeted unit tests for audio_analysis.py: the startup-time
pending-analysis requeue (see app.main's lifespan and
requeue_pending_analysis's own docstring for why a plain "still pending"
check is sufficient recovery under the current analysis_status model -- no
intermediate "processing" state exists, so a stranded row is always
exactly "pending"), the Krumhansl-Schmuckler key-finding algorithm/Camelot
lookup (_estimate_key, camelot_for), and beat-grid timing (_beat_grids)
against known-key/known-tempo synthetic signals -- the full upload-driven
analysis pipeline is tested separately in test_catalog.py, which can't
isolate "does the algorithm actually get the right answer" from everything
else an upload does."""

from queue import Full

import numpy as np
import pytest

from app.database.models.catalog import CatalogTrack
from app.services import audio_analysis
from app.services import upload_queue as uq_module
from app.services.audio_analysis import (
    _BARS_PER_PHRASE,
    _BEATS_PER_BAR,
    _MAJOR_KEY_PROFILE,
    _MINOR_KEY_PROFILE,
    _PITCH_CLASSES,
    _beat_grids,
    _estimate_key,
    camelot_for,
)


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


# --- Krumhansl-Schmuckler key-finding + Camelot lookup --------------------


def _chroma_from_profile(profile: np.ndarray, frames: int = 20) -> np.ndarray:
    """A fake chroma matrix (12, frames) whose column-mean is exactly
    `profile` -- _estimate_key only ever reads chroma.mean(axis=1), so
    tiling a profile across frames is a faithful, minimal fixture for
    testing the correlation logic in isolation from real signal
    processing (see test_estimate_key_recovers_c_major_from_a_real_signal
    below for an end-to-end check against genuine synthesized audio)."""

    return np.tile(profile.reshape(-1, 1), (1, frames))


@pytest.mark.parametrize("shift", range(12))
def test_estimate_key_recovers_every_rotation_of_a_pure_major_profile(shift):
    chroma = _chroma_from_profile(np.roll(_MAJOR_KEY_PROFILE, shift))
    pitch_class, mode, confidence = _estimate_key(chroma)
    assert pitch_class == _PITCH_CLASSES[shift]
    assert mode == "major"
    assert confidence > 0.0


@pytest.mark.parametrize("shift", range(12))
def test_estimate_key_recovers_every_rotation_of_a_pure_minor_profile(shift):
    chroma = _chroma_from_profile(np.roll(_MINOR_KEY_PROFILE, shift))
    pitch_class, mode, confidence = _estimate_key(chroma)
    assert pitch_class == _PITCH_CLASSES[shift]
    assert mode == "minor"
    assert confidence > 0.0


def test_estimate_key_confidence_is_zero_for_a_perfectly_flat_ambiguous_profile():
    # Every pitch class equally present -- _correlate's zero-variance guard
    # makes every one of the 24 template correlations exactly 0.0, so the
    # winner and runner-up tie exactly: maximal, honest ambiguity, not an
    # arbitrary tiebreak dressed up as a confidence number.
    chroma = _chroma_from_profile(np.ones(12))
    _, _, confidence = _estimate_key(chroma)
    assert confidence == 0.0


def test_estimate_key_recovers_c_major_from_a_real_synthesized_signal():
    # A genuine audio signal (not a hand-fed chroma array): one sine tone
    # per pitch class, amplitude-weighted by the C-major Krumhansl profile
    # itself -- a deliberately "sounds like C major" signal -- run through
    # real librosa.feature.chroma_cqt extraction. Proves the full pipeline
    # (real chroma extraction feeding _estimate_key), not just the
    # correlation math the profile-level tests above already cover.
    import librosa

    sr = 22050
    duration = 4.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    base_frequency = 261.63  # C4
    signal = np.zeros_like(t)
    for index, weight in enumerate(_MAJOR_KEY_PROFILE):
        frequency = base_frequency * (2 ** (index / 12))
        signal += weight * np.sin(2 * np.pi * frequency * t)
    signal = (signal / np.max(np.abs(signal))).astype(np.float32)

    chroma = librosa.feature.chroma_cqt(y=signal, sr=sr)
    pitch_class, mode, confidence = _estimate_key(chroma)
    assert pitch_class == "C"
    assert mode == "major"
    assert confidence > 0.0


def test_camelot_for_matches_a_cross_checked_reference_table():
    # Spot-checked against two independent published Camelot wheel
    # references (see _CAMELOT_MAJOR/_CAMELOT_MINOR's own comment in
    # audio_analysis.py) -- these are the exact points both sources agreed
    # on.
    assert camelot_for("C", "major") == "8B"
    assert camelot_for("A", "minor") == "8A"
    assert camelot_for("G", "major") == "9B"
    assert camelot_for("F", "major") == "7B"
    assert camelot_for("E", "minor") == "9A"
    assert camelot_for("D", "minor") == "7A"
    assert camelot_for("C", "minor") == "5A"


def test_camelot_for_every_major_key_shares_its_number_with_its_relative_minor():
    # A structural property of the Camelot wheel itself, true regardless of
    # which reference table it's checked against: every major key's
    # relative minor (3 semitones down) shares its number -- only the
    # letter changes (e.g. 8B <-> 8A).
    for index, pitch_class in enumerate(_PITCH_CLASSES):
        major_code = camelot_for(pitch_class, "major")
        relative_minor_pitch_class = _PITCH_CLASSES[(index - 3) % 12]
        minor_code = camelot_for(relative_minor_pitch_class, "minor")
        assert major_code[:-1] == minor_code[:-1]
        assert major_code[-1] == "B"
        assert minor_code[-1] == "A"


def test_camelot_for_returns_none_for_unrecognized_input():
    assert camelot_for("H", "major") is None
    assert camelot_for("C", "dorian") is None
    assert camelot_for(None, "major") is None
    assert camelot_for("C", None) is None


# --- Beat-grid timing (_beat_grids) ----------------------------------------


def _synthetic_click_track(bpm: float, duration_seconds: float, sr: int) -> np.ndarray:
    """A clean click track at an *exactly* known tempo: short, fast-decaying
    sine bursts at the beat period implied by `bpm` -- the standard fixture
    shape for testing a beat tracker's timestamp accuracy against a known
    ground truth, not real music."""

    beat_period = 60.0 / bpm
    n_samples = int(duration_seconds * sr)
    signal = np.zeros(n_samples, dtype=np.float64)
    click_duration = 0.05
    click_samples = int(click_duration * sr)
    t_click = np.linspace(0, click_duration, click_samples, endpoint=False)
    click = np.exp(-40 * t_click) * np.sin(2 * np.pi * 1000 * t_click)

    beat_time = 0.0
    while beat_time < duration_seconds:
        start = int(beat_time * sr)
        end = min(start + click_samples, n_samples)
        signal[start:end] += click[: end - start]
        beat_time += beat_period
    return signal.astype(np.float32)


@pytest.mark.parametrize("bpm", [90.0, 120.0, 140.0])
def test_beat_grid_timestamps_land_within_tolerance_of_a_known_tempo_click_track(bpm):
    import librosa

    sr = 22050
    hop_length = 512
    signal = _synthetic_click_track(bpm, duration_seconds=20.0, sr=sr)

    onset_envelope = librosa.onset.onset_strength(y=signal, sr=sr, hop_length=hop_length)
    _, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope, sr=sr, hop_length=hop_length
    )
    beat_grid, downbeat_grid, phrase_boundaries = _beat_grids(librosa, beat_frames, sr, hop_length)

    assert len(beat_grid) > 10  # sanity: real beats were actually found, not an empty result

    expected_period = 60.0 / bpm
    # Edge beats near the very start/end of a clip are where a beat
    # tracker's windowing is most likely to clip a partial period -- the
    # standard MIR-evaluation practice (e.g. mir_eval's beat metrics) is
    # to trim them before checking timestamp accuracy, so one legitimate
    # boundary artifact doesn't look like a tracking failure.
    interior_beats = beat_grid[1:-1]
    intervals = np.diff(interior_beats)
    # Every interior inter-beat interval lands within 50ms of the known,
    # exact click-track period -- genuine timestamp accuracy against
    # ground truth, not just "some list got produced."
    assert np.allclose(intervals, expected_period, atol=0.05)

    # downbeat_grid/phrase_boundaries are exactly the declared coarse
    # heuristic -- fixed-stride slices of beat_grid, nothing more.
    assert downbeat_grid == beat_grid[::_BEATS_PER_BAR]
    assert phrase_boundaries == downbeat_grid[::_BARS_PER_PHRASE]


def test_beat_grids_are_empty_lists_not_none_when_no_beats_are_found():
    # A silent/beatless clip: beat_track can legitimately return zero
    # beats. [] is the honest result -- distinct from None, which this
    # pipeline reserves for "analysis never completed" (see
    # CatalogTrack.beat_grid_json's own docstring).
    beat_grid, downbeat_grid, phrase_boundaries = _beat_grids(
        librosa_module=_FrameToTimeStub(), beat_frames=np.array([]), sr=22050, hop_length=512
    )
    assert beat_grid == []
    assert downbeat_grid == []
    assert phrase_boundaries == []


class _FrameToTimeStub:
    """A minimal stand-in for the `librosa` module argument _beat_grids
    takes by reference (not a global import) -- only frames_to_time is
    ever called, and an empty beat_frames array never needs a real
    sample-rate/hop-length conversion to produce an empty result."""

    @staticmethod
    def frames_to_time(frames, sr, hop_length):
        return np.array([])
