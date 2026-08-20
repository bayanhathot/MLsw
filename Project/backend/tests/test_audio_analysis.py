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
import soundfile as sf

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.services import audio_analysis
from app.services import upload_queue as uq_module
from app.services.pipeline import external_track_cache as etc_module
from app.services.audio_analysis import (
    _BARS_PER_PHRASE,
    _BEATS_PER_BAR,
    _CHROMA_HOP_LENGTH,
    _MAJOR_KEY_PROFILE,
    _MINOR_KEY_PROFILE,
    _PITCH_CLASSES,
    _SILENCE_FLOOR_DBFS,
    _TARGET_SEGMENT_SECONDS,
    _beat_grids,
    _best_segment,
    _bucket_chroma,
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


def _make_external_track(db_session, **overrides) -> ExternalTrack:
    fields = {
        "source": "audius",
        "external_id": "stranded-1",
        "title": "Stranded External Track",
        "artist": "Test Artist",
        "analysis_status": "pending",
    }
    fields.update(overrides)
    row = ExternalTrack(**fields)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_requeue_pending_external_analysis_resubmits_a_stranded_track(db_session, monkeypatch):
    monkeypatch.setattr(etc_module, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    track = _make_external_track(db_session)

    calls = []
    monkeypatch.setattr(
        uq_module.upload_queue, "submit_external_analysis", lambda track_id: calls.append(track_id)
    )

    requeued = audio_analysis.requeue_pending_external_analysis()

    assert requeued == 1
    assert calls == [track.id]


def test_requeue_pending_external_analysis_is_noop_when_flag_disabled(db_session, monkeypatch):
    monkeypatch.setattr(etc_module, "AUDIUS_ANALYSIS_CACHE_ENABLED", False)
    _make_external_track(db_session)

    calls = []
    monkeypatch.setattr(
        uq_module.upload_queue, "submit_external_analysis", lambda track_id: calls.append(track_id)
    )

    requeued = audio_analysis.requeue_pending_external_analysis()

    assert requeued == 0
    assert calls == []


def test_requeue_pending_external_analysis_ignores_non_pending_rows(db_session, monkeypatch):
    monkeypatch.setattr(etc_module, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    _make_external_track(db_session, external_id="completed-1", title="Completed", analysis_status="completed")
    _make_external_track(db_session, external_id="failed-1", title="Failed", analysis_status="failed")

    calls = []
    monkeypatch.setattr(
        uq_module.upload_queue, "submit_external_analysis", lambda track_id: calls.append(track_id)
    )

    requeued = audio_analysis.requeue_pending_external_analysis()

    assert requeued == 0
    assert calls == []


def test_requeue_pending_external_analysis_continues_past_a_full_queue(db_session, monkeypatch):
    monkeypatch.setattr(etc_module, "AUDIUS_ANALYSIS_CACHE_ENABLED", True)
    first = _make_external_track(db_session, external_id="first-1", title="First")
    second = _make_external_track(db_session, external_id="second-1", title="Second")

    calls = []

    def fake_submit_external_analysis(track_id):
        if track_id == first.id:
            raise Full
        calls.append(track_id)

    monkeypatch.setattr(uq_module.upload_queue, "submit_external_analysis", fake_submit_external_analysis)

    requeued = audio_analysis.requeue_pending_external_analysis()

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


# --- Energy floor in segment selection (_best_segment) --------------------


def _chroma_rms_peak(signal: np.ndarray, sr: int):
    """Real librosa extraction (chroma_cqt + rms), at the exact hop length
    _best_segment expects its two inputs bucketed at -- the same call
    sequence analyze_audio() itself runs, just without loading a file."""

    import librosa

    chroma = librosa.feature.chroma_cqt(y=signal, sr=sr, hop_length=_CHROMA_HOP_LENGTH)
    frames_per_second = sr / _CHROMA_HOP_LENGTH
    rms_frames = librosa.feature.rms(y=signal, hop_length=_CHROMA_HOP_LENGTH)[0]
    peak_amplitude = float(np.max(np.abs(signal))) if signal.size else 0.0
    return chroma, frames_per_second, rms_frames, peak_amplitude


def test_best_segment_never_selects_a_near_silent_region_over_a_loud_one():
    # Deliberately adversarial for chroma-similarity-only ranking: the loud
    # region is harmonically *varied* (an arpeggio, so only moderately
    # self-similar to itself), while the quiet region is a single sustained
    # tone -- maximally self-similar, but far too quiet to be a real
    # highlight. Confirmed below that pure similarity (no energy floor)
    # actually picks a window inside the quiet region for this exact
    # signal, so this isn't a strawman -- it's the failure mode
    # _SILENCE_FLOOR_DBFS exists to close.
    sr = 22050
    loud_seconds = 40
    quiet_seconds = 40
    t_loud = np.linspace(0, loud_seconds, int(sr * loud_seconds), endpoint=False)
    freqs = 220.0 * (2 ** (np.floor(t_loud * 2) % 12 / 12))
    loud = (0.8 * np.sin(2 * np.pi * freqs * t_loud)).astype(np.float32)
    t_quiet = np.linspace(0, quiet_seconds, int(sr * quiet_seconds), endpoint=False)
    quiet = (0.0003 * np.sin(2 * np.pi * 220.0 * t_quiet)).astype(np.float32)
    signal = np.concatenate([loud, quiet])
    duration_seconds = len(signal) / sr

    chroma, frames_per_second, rms_frames, peak_amplitude = _chroma_rms_peak(signal, sr)

    # What pure chroma self-similarity alone (no energy floor) would pick --
    # proves the scenario is genuinely adversarial, not incidentally safe.
    buckets = _bucket_chroma(chroma, frames_per_second)
    total_seconds = buckets.shape[1]
    window = min(total_seconds, _TARGET_SEGMENT_SECONDS)
    norms = buckets / (np.linalg.norm(buckets, axis=0, keepdims=True) + 1e-9)
    similarity = norms.T @ norms
    naive_start, naive_score = 0, -1.0
    for start in range(0, total_seconds - window + 1):
        score = float(similarity[start : start + window, :].mean())
        if score > naive_score:
            naive_score, naive_start = score, start
    assert naive_start >= loud_seconds, (
        "test setup didn't reproduce the vulnerability: pure similarity "
        "should have picked a window entirely inside the quiet region"
    )

    start, end, method, level = _best_segment(
        chroma, frames_per_second, duration_seconds, rms_frames, peak_amplitude
    )

    assert method == "chorus_detection"
    assert level is not None
    assert level >= _SILENCE_FLOOR_DBFS
    # The energy floor actually changed the outcome versus naive similarity.
    assert start != naive_start


def test_best_segment_signals_all_windows_below_floor_distinctly_from_whole_clip(tmp_path):
    # D2/Cause B: this used to assert method == "whole_clip" here -- the
    # defect itself, since that's indistinguishable from the legitimate
    # too-short-to-window case and lets analyze_audio() report a uniformly
    # near-silent track's entire duration as a *completed* analysis. The
    # sentinel is intercepted by analyze_audio() (see the test below) and
    # never reaches a DB row.
    sr = 22050
    duration_seconds = 90.0
    signal = np.zeros(int(sr * duration_seconds), dtype=np.float32)

    chroma, frames_per_second, rms_frames, peak_amplitude = _chroma_rms_peak(signal, sr)

    start, end, method, level = _best_segment(
        chroma, frames_per_second, duration_seconds, rms_frames, peak_amplitude
    )

    assert method == "all_windows_below_silence_floor"
    assert level is None


def test_analyze_audio_raises_rather_than_completing_on_a_uniformly_silent_track(tmp_path):
    # The sentinel above must never reach a persisted AnalysisResult --
    # analyze_audio() itself raises, so both analyze_catalog_track and
    # analyze_external_track's existing except-branches turn a uniformly
    # near-silent track into an ordinary "failed" analysis (same
    # retry/fallback machinery every other analysis failure already uses)
    # rather than ever reporting it "completed".
    sr = 22050
    duration_seconds = 90
    silence = np.zeros(sr * duration_seconds, dtype=np.float32)
    path = tmp_path / "silent.wav"
    sf.write(str(path), silence, sr)

    with pytest.raises(ValueError, match="silence floor"):
        audio_analysis.analyze_audio(str(path), label="test silent track")


def test_analyze_catalog_track_marks_a_uniformly_silent_upload_failed_not_completed(db_session, tmp_path):
    # D2/Cause B, end to end: the raise above must actually reach a
    # persisted CatalogTrack row as analysis_status="failed", not
    # "completed" -- proving the sentinel never silently reaches the DB
    # via analyze_catalog_track's own existing (pre-existing, unmodified)
    # except-branch.
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    sr = 22050
    duration_seconds = 90
    silence = np.zeros(sr * duration_seconds, dtype=np.float32)
    sf.write(str(catalog_dir / "silent.wav"), silence, sr)

    row = CatalogTrack(
        title="Silent", artist="Someone", storage_name="silent.wav", content_type="audio/wav",
        duration_seconds=duration_seconds, analysis_status="pending",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    audio_analysis.analyze_catalog_track(row.id)

    db_session.refresh(row)
    assert row.analysis_status == "failed"
    assert row.segment_start_second is None  # _apply_result never ran


def test_best_segment_still_ranks_normally_among_windows_that_all_pass_the_floor():
    # A real, uniformly-loud signal with varying harmonic content -- proves
    # the floor doesn't change behavior when every candidate window is
    # legitimately audible, only when some aren't.
    sr = 22050
    duration_seconds = 60.0
    t = np.linspace(0, duration_seconds, int(sr * duration_seconds), endpoint=False)
    freqs = 220.0 * (2 ** (np.floor(t * 0.5) % 12 / 12))
    signal = (0.7 * np.sin(2 * np.pi * freqs * t)).astype(np.float32)

    chroma, frames_per_second, rms_frames, peak_amplitude = _chroma_rms_peak(signal, sr)

    start, end, method, level = _best_segment(
        chroma, frames_per_second, duration_seconds, rms_frames, peak_amplitude
    )

    assert method == "chorus_detection"
    assert level is not None and level >= _SILENCE_FLOOR_DBFS
    assert end - start == min(int(duration_seconds), _TARGET_SEGMENT_SECONDS)


# --- Long-track analysis window cap (_MAX_ANALYSIS_SECONDS) ---------------


def test_analyze_audio_can_select_a_highlight_past_the_old_four_minute_cap(tmp_path):
    # Regression guard for the original _MAX_ANALYSIS_SECONDS=240 bug:
    # librosa.load's own duration= truncated every downstream call
    # (chroma, beat tracking, _best_segment) to the first 4 minutes, so a
    # highlight anywhere past 4:00 -- routine for the product's own
    # Emotional/Tarab mode -- could never be selected, full stop. 280s
    # total (past the old 240s cap, within the new 600s one): 250s of a
    # fast-pitch-drifting filler (deliberately low self-similarity within
    # any 30s window) followed by a 30s tight, perfectly repeating loop
    # (maximally self-similar) starting at 250s -- unambiguously the
    # "best segment" on chroma-similarity grounds alone, reachable only if
    # analyze_audio actually looked past 4:00.
    sr = 22050
    filler_seconds = 250
    highlight_seconds = 30

    t_filler = np.linspace(0, filler_seconds, int(sr * filler_seconds), endpoint=False)
    freq_drift = 220.0 * (2 ** (np.floor(t_filler / 3.0) % 12 / 12))
    filler = (0.5 * np.sin(2 * np.pi * freq_drift * t_filler)).astype(np.float32)

    loop_seconds = 1.0
    t_loop = np.linspace(0, loop_seconds, int(sr * loop_seconds), endpoint=False)
    loop = (0.7 * np.sin(2 * np.pi * 440.0 * t_loop)).astype(np.float32)
    highlight = np.tile(loop, int(highlight_seconds / loop_seconds))

    signal = np.concatenate([filler, highlight]).astype(np.float32)
    path = tmp_path / "long_track.wav"
    sf.write(str(path), signal, sr)

    result = audio_analysis.analyze_audio(str(path), label="long track test")

    assert result.segment_method == "chorus_detection"
    # The winning window must start at/after the old 240s cap -- proof the
    # highlight (which only exists past 250s) was actually reachable, not
    # just that *some* window won.
    assert result.segment_start_second >= 240
    assert result.segment_level_dbfs is not None
    assert result.segment_level_dbfs >= audio_analysis._SILENCE_FLOOR_DBFS


def test_analyze_audio_finds_a_highlight_past_the_current_ten_minute_cap(monkeypatch, tmp_path):
    # D3: _MAX_ANALYSIS_SECONDS is still the bpm/key/beat-grid prefix, but
    # no longer the ceiling on segment selection -- a track whose only real
    # highlight sits well past that prefix (routine for an 8-20 minute
    # Emotional/Tarab track) must still find it, via
    # _select_long_track_segment's sampling of the remainder past the
    # prefix.
    #
    # Every relevant constant is monkeypatched to 1/20th of its real
    # default (_MAX_ANALYSIS_SECONDS 600->40, _TARGET_SEGMENT_SECONDS
    # 30->3, _LONG_TRACK_REMAINDER_CHUNK_SECONDS 75->15) so this exercises
    # the exact same code path -- the arithmetic is all relative to these
    # constants, not hardcoded -- while keeping real decode/DSP cost (the
    # dominant cost, not signal generation) proportionally down too; at
    # full scale this fixture would need a genuine ~15-minute signal and
    # take proportionally longer to decode than the suite's per-test
    # budget comfortably allows.
    monkeypatch.setattr(audio_analysis, "_MAX_ANALYSIS_SECONDS", 40)
    monkeypatch.setattr(audio_analysis, "_TARGET_SEGMENT_SECONDS", 3)
    monkeypatch.setattr(audio_analysis, "_LONG_TRACK_REMAINDER_CHUNK_SECONDS", 15)

    sr = 22050
    # _LONG_TRACK_REMAINDER_CHUNKS defaults to 4, tiling [40s, 100s) into
    # 15s chunks: [40,55), [55,70), [70,85), [85,100). The highlight sits
    # at [75s, 78s), inside the third chunk, comfortably past both the 40s
    # prefix and the first two remainder chunks -- reachable only if
    # sampling genuinely covers the whole remainder, not just its start.
    filler_before_seconds = 75
    highlight_seconds = 3
    filler_after_seconds = 22

    def _drifting_filler(seconds: float) -> np.ndarray:
        t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
        freq_drift = 220.0 * (2 ** (np.floor(t / 3.0) % 12 / 12))
        return (0.5 * np.sin(2 * np.pi * freq_drift * t)).astype(np.float32)

    loop_seconds = 1.0
    t_loop = np.linspace(0, loop_seconds, int(sr * loop_seconds), endpoint=False)
    loop = (0.7 * np.sin(2 * np.pi * 440.0 * t_loop)).astype(np.float32)
    highlight = np.tile(loop, int(highlight_seconds / loop_seconds))

    signal = np.concatenate([
        _drifting_filler(filler_before_seconds),
        highlight,
        _drifting_filler(filler_after_seconds),
    ]).astype(np.float32)
    path = tmp_path / "very_long_track.wav"
    sf.write(str(path), signal, sr)

    result = audio_analysis.analyze_audio(str(path), label="very long track test")

    assert result.segment_method == "chorus_detection"
    # The winning window must start at/after the 40s prefix -- proof the
    # highlight (which only exists past 75s) was actually reachable past
    # it, not just that *some* window inside the prefix won.
    assert result.segment_start_second >= 40
    assert result.segment_level_dbfs is not None
    assert result.segment_level_dbfs >= audio_analysis._SILENCE_FLOOR_DBFS
