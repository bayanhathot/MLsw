"""The one-time BPM/key/best-segment analysis job for a catalog track.

Triggered from upload_queue.py's worker right after a catalog-track upload
finishes storing its bytes (requirement 5: reuse that queue, no second async
system). Opens its own short-lived DB session -- the same pattern
cleanup_uploads.py/seed.py use outside request scope, since this runs on a
queue worker thread, not inside a request. Accessed as `db_module.SessionLocal`
(not a direct name import) so tests can point it at the same engine `get_db`
is overridden to use -- a plain import would freeze the pre-override binding.

Chorus/hook detection is a self-similarity proxy: chroma features are
bucketed to ~1 column per second (bounding the similarity matrix regardless
of track length), and the window with the highest average similarity to the
rest of the track -- i.e. the most repeated/representative section -- is
picked. Key detection is real Krumhansl-Schmuckler-style key-finding: the
mean chroma profile is correlated against 24 rotated major/minor
key-profile templates and the best-correlating (root, mode) pair wins --
see _estimate_key. Beat-grid timing (beat_grid/downbeat_grid/
phrase_boundaries) is derived from librosa.beat.beat_track's own beat-frame
output -- already computed to derive bpm, never a second onset-detection
pass; only the beat grid itself is genuine data, downbeat_grid/
phrase_boundaries are a coarse fixed-meter heuristic layered on top of it,
not real meter/structure detection -- see _beat_grids. All of the above are
deterministic signal-processing, not a trained model.
"""

import logging
from queue import Full

import numpy as np

from app.core.time import utc_now
from app.database import database as db_module
from app.database.models.catalog import CatalogTrack
from app.services import upload_queue
from app.services.pipeline.catalog_retriever import CATALOG_AUDIO_SUBDIR

logger = logging.getLogger(__name__)

# Bump this whenever the analysis approach below changes (a different
# chroma/beat-tracking method, a different segment-selection heuristic,
# etc.) so existing rows can be targeted for reprocessing by version later
# -- see CatalogTrack.analysis_version's own docstring for the query shape
# this is meant to support. "v2" (bumped from "v1"): musical_key is now
# real Krumhansl-Schmuckler key-finding (root + mode), replacing v1's bare
# strongest-average-chroma-bin heuristic -- a genuine change to the
# analysis approach, not just an additive field (contrast with
# integrated_loudness_lufs, an independent measurement that didn't touch
# bpm/key/segment logic and so didn't warrant a bump).
ANALYSIS_VERSION = "v2"

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl & Kessler (1982) major/minor key profiles: empirically measured
# listener probe-tone ratings of how well each pitch class fits a
# previously established key context, indexed like _PITCH_CLASSES (index 0
# = the tonic's own rating). The standard reference values for
# Krumhansl-Schmuckler-style key-finding -- cross-checked against the
# Krumhansl-Schmuckler Key Profiler reference implementation
# (mashav.com/sha/praat/scripts/Krumhansl-Schmuckler_Key_Profiler.html) and
# multiple published MIR sources, not hand-derived from memory.
_MAJOR_KEY_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_KEY_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

# Camelot wheel notation (DJ-style harmonic-mixing shorthand for a key --
# e.g. "8B" for C major). Cross-checked against two independent published
# Camelot references, agreeing on every value checked (the circle-of-fifths
# ordering F=7B/C=8B/G=9B/..., and every major key's relative minor sharing
# its number, e.g. C major=8B <-> A minor=8A) -- not hand-derived. Not
# wired into TransitionPlanner yet -- CatalogTrack storage only.
_CAMELOT_MAJOR = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
    "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B",
}
_CAMELOT_MINOR = {
    "C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A", "F": "4A",
    "F#": "11A", "G": "6A", "G#": "1A", "A": "8A", "A#": "3A", "B": "10A",
}
# Bounds CPU/memory for a pathologically long upload; analysis only needs
# enough of the track to find one representative ~30s window.
_MAX_ANALYSIS_SECONDS = 240
_TARGET_SEGMENT_SECONDS = 30
_CHROMA_HOP_LENGTH = 512
_BEAT_HOP_LENGTH = 512  # matches librosa.beat.beat_track's own default
# librosa.feature.tempo's own default autocorrelation window, in seconds --
# matched here so _bpm_confidence reads the tempogram at the same
# resolution beat_track's internal tempo estimate was chosen from.
_TEMPO_AUTOCORRELATION_SECONDS = 8.0
# Coarse, fixed-meter assumptions used to derive downbeat_grid/
# phrase_boundaries from beat_track's own beat grid -- see _beat_grids'
# docstring for why these are heuristics, not real meter/structure
# detection (librosa.beat.beat_track has no concept of either).
_BEATS_PER_BAR = 4
_BARS_PER_PHRASE = 8


def camelot_for(pitch_class: str | None, mode: str | None) -> str | None:
    """Deterministic (pitch_class, mode) -> Camelot code lookup, e.g.
    ("C", "major") -> "8B" (see _CAMELOT_MAJOR/_CAMELOT_MINOR). None for an
    unrecognized pitch_class/mode pair, or either input missing -- never a
    guessed/default code."""

    if pitch_class is None or mode is None:
        return None
    table = {"major": _CAMELOT_MAJOR, "minor": _CAMELOT_MINOR}.get(mode)
    return table.get(pitch_class) if table is not None else None


def _correlate(profile: np.ndarray, template: np.ndarray) -> float:
    """Pearson correlation between the observed mean chroma profile and one
    rotated key-profile template -- the core of Krumhansl-Schmuckler
    key-finding: whichever template correlates best with what was actually
    played is the most likely key. 0.0 (never a guessed correlation) if
    either side has zero variance -- corrcoef is undefined (NaN) for a
    constant input, which a completely flat/silent chroma profile can
    produce."""

    if np.std(profile) == 0 or np.std(template) == 0:
        return 0.0
    return float(np.corrcoef(profile, template)[0, 1])


def _estimate_key(chroma: np.ndarray) -> tuple[str, str, float]:
    """Krumhansl-Schmuckler-style key-finding: correlates the track's mean
    chroma profile against all 24 rotated major/minor key-profile
    templates (_MAJOR_KEY_PROFILE/_MINOR_KEY_PROFILE, one rotation per
    possible tonic) and picks the single best-correlating (root, mode)
    pair -- replacing the old bare strongest-average-chroma-bin heuristic,
    which only ever guessed a pitch class and had no concept of mode at
    all. A template rotated by `shift` semitones represents that pitch
    class as the tonic: np.roll(template, shift)[i] == template[(i -
    shift) % 12], i.e. each pitch class's fit rating is read at its
    interval-from-tonic distance, exactly matching how the original
    Krumhansl-Kessler profiles are defined (index 0 = the tonic's own
    rating).

    Returns (pitch_class, mode, confidence). confidence is the correlation
    margin between the winning template and its runner-up (which is very
    often the *same* root's opposite mode, or a closely related key --
    dominant/subdominant/relative -- since those templates are the most
    similar to the winner by construction), clipped to [0.0, 1.0]: a
    genuinely low margin means two templates fit the observed chroma
    almost equally well, not an invented uncertainty number. Reuses
    exactly the shape the old, narrower _key_confidence (chroma-energy
    margin between the top two pitch-class bins) used, just computed from
    the real key-correlation scores instead -- one confidence field for
    the whole key decision, not two inconsistent ones."""

    profile = chroma.mean(axis=1)
    scores = []
    for mode, template in (("major", _MAJOR_KEY_PROFILE), ("minor", _MINOR_KEY_PROFILE)):
        for shift in range(12):
            rotated = np.roll(template, shift)
            scores.append((_correlate(profile, rotated), _PITCH_CLASSES[shift], mode))
    scores.sort(key=lambda item: item[0], reverse=True)
    best_score, best_pitch_class, best_mode = scores[0]
    runner_up_score = scores[1][0]
    confidence = float(np.clip(best_score - runner_up_score, 0.0, 1.0))
    return best_pitch_class, best_mode, confidence


def _bpm_confidence(
    librosa_module, onset_envelope: np.ndarray, sr: float, hop_length: int, tempo_bpm: float
) -> float:
    """A confidence-like signal for the chosen tempo, read from the same
    onset-strength autocorrelation beat_track uses internally to pick that
    tempo in the first place (see librosa.feature.tempo's implementation,
    which beat_track calls directly) -- not an invented number.
    librosa.feature.tempogram normalizes every analyzed window so its own
    strongest periodicity is exactly 1.0; this is the *average*, across
    every window, of that normalized strength specifically at the chosen
    tempo's lag. 1.0 would mean every single window's strongest
    periodicity coincided exactly with the chosen tempo (about as
    confident as this signal can get); values near 0.0 mean the chosen
    tempo was rarely the dominant periodicity window-to-window -- a
    genuinely weak/ambiguous beat, not noise in the measurement. Verified
    directionally against a synthetic click track (clean, strongly
    periodic input scores far higher than typical program material)."""

    win_length = int(
        librosa_module.time_to_frames(_TEMPO_AUTOCORRELATION_SECONDS, sr=sr, hop_length=hop_length)
    )
    tempogram = librosa_module.feature.tempogram(
        onset_envelope=onset_envelope, sr=sr, hop_length=hop_length, win_length=win_length
    )
    mean_tempogram = tempogram.mean(axis=-1)
    bpm_bins = librosa_module.tempo_frequencies(len(mean_tempogram), sr=sr, hop_length=hop_length)
    closest_bin = int(np.argmin(np.abs(bpm_bins - tempo_bpm)))
    return float(np.clip(mean_tempogram[closest_bin], 0.0, 1.0))


def _beat_grids(
    librosa_module, beat_frames: np.ndarray, sr: float, hop_length: int
) -> tuple[list[float], list[float], list[float]]:
    """Converts beat_track's own beat-frame output (already computed to
    derive bpm -- see analyze_catalog_track, previously discarded as `_`)
    into three second-timestamp lists, reusing that exact data rather than
    running a second onset-detection/beat-tracking pass:

    - beat_grid: every detected beat, genuine data straight from
      librosa.beat.beat_track -- no heuristic involved.
    - downbeat_grid: every _BEATS_PER_BAR-th beat, starting from the
      first. librosa's beat_track has no concept of meter or bar position
      at all -- this is a COARSE HEURISTIC assuming constant 4/4 time (the
      overwhelmingly common case for this catalog's likely content), not
      genuine downbeat detection. A track in 3/4, or with a meter change
      partway through, will have this drift out of alignment with the
      music's real bar lines.
    - phrase_boundaries: every _BARS_PER_PHRASE-th downbeat (so every
      _BEATS_PER_BAR * _BARS_PER_PHRASE beats). The same caveat, one level
      further removed -- an even coarser heuristic layered on top of the
      already-heuristic downbeat_grid (8-bar phrases are common in
      EDM/pop but far from universal), not real structural/section
      analysis. Building a genuine downbeat/phrase (meter-aware
      bar-tracking, self-similarity-based structure segmentation) model
      is out of scope here -- see this function's own name.

    All three are [] (not None) when beat_track found no beats at all -- a
    real, if uneventful, result, not a sign analysis didn't run."""

    beat_seconds = librosa_module.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)
    beat_grid = [round(float(t), 3) for t in beat_seconds]
    downbeat_grid = beat_grid[::_BEATS_PER_BAR]
    phrase_boundaries = downbeat_grid[::_BARS_PER_PHRASE]
    return beat_grid, downbeat_grid, phrase_boundaries


def _bucket_chroma(chroma: np.ndarray, frames_per_second: float) -> np.ndarray:
    """Reduce frame-level chroma to ~one column per second, so the
    self-similarity matrix below stays small no matter the source hop
    length or track duration."""

    bucket_frames = max(1, int(round(frames_per_second)))
    total_frames = chroma.shape[1]
    n_buckets = max(1, total_frames // bucket_frames)
    trimmed = chroma[:, : n_buckets * bucket_frames]
    return trimmed.reshape(chroma.shape[0], n_buckets, bucket_frames).mean(axis=2)


def _best_segment(
    chroma: np.ndarray, frames_per_second: float, duration_seconds: float
) -> tuple[int, int, str]:
    buckets = _bucket_chroma(chroma, frames_per_second)
    total_seconds = buckets.shape[1]
    window = min(total_seconds, _TARGET_SEGMENT_SECONDS)
    if total_seconds <= window or window <= 0:
        return 0, max(1, int(duration_seconds)), "whole_clip"

    norms = buckets / (np.linalg.norm(buckets, axis=0, keepdims=True) + 1e-9)
    similarity = norms.T @ norms  # second-by-second cosine self-similarity

    best_start, best_score = 0, -1.0
    for start in range(0, total_seconds - window + 1):
        score = float(similarity[start : start + window, :].mean())
        if score > best_score:
            best_score, best_start = score, start
    return best_start, best_start + window, "chorus_detection"


def _integrated_loudness_lufs(waveform: np.ndarray, sr: float, catalog_track_id: int) -> float | None:
    """ITU-R BS.1770 integrated loudness of the already-loaded waveform, via
    pyloudnorm -- measured once here over the whole (up to
    _MAX_ANALYSIS_SECONDS) analyzed clip, never re-measured per segment or
    per crossfade at render time (see CatalogTrack.integrated_loudness_lufs'
    own docstring for why; audio_renderer.py just applies a flat gain
    derived from this stored value instead). Kept in its own try/except,
    separate from analyze_catalog_track's own -- a loudness-measurement
    failure (e.g. BS.1770's gating finds no audio above the -70 LUFS
    absolute threshold, on a near-silent clip) must not invalidate the
    bpm/key/segment results that succeeded independently of it. None on any
    failure or non-finite result, matching this pipeline's established
    missing-signal handling (see this column's docstring)."""

    try:
        import pyloudnorm

        meter = pyloudnorm.Meter(int(sr))
        loudness = meter.integrated_loudness(waveform)
    except Exception as exc:
        logger.warning(
            "Catalog track %s loudness measurement failed: %s", catalog_track_id, exc
        )
        return None
    return round(loudness, 2) if np.isfinite(loudness) else None


def analyze_catalog_track(catalog_track_id: int) -> None:
    # Imported lazily: librosa pulls in a heavy dependency tree (numpy/scipy/
    # numba/soundfile) that only the analysis job needs, not every process
    # that imports app.services.audio_analysis.
    import librosa

    with db_module.SessionLocal() as db:
        row = db.query(CatalogTrack).filter(CatalogTrack.id == catalog_track_id).first()
        if row is None:
            return
        path = upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / row.storage_name
        try:
            waveform, sr = librosa.load(
                str(path), sr=None, mono=True, duration=_MAX_ANALYSIS_SECONDS
            )
            duration_seconds = librosa.get_duration(y=waveform, sr=sr)
            # Computed explicitly (rather than passing y= straight to
            # beat_track) only so _bpm_confidence can read the same
            # onset-strength signal beat_track uses internally to choose
            # its tempo -- otherwise identical to beat_track(y=waveform,
            # sr=sr)'s own default behavior (aggregate=np.median,
            # hop_length=512), so the tempo output itself is unchanged.
            onset_envelope = librosa.onset.onset_strength(
                y=waveform, sr=sr, hop_length=_BEAT_HOP_LENGTH, aggregate=np.median
            )
            tempo, beat_frames = librosa.beat.beat_track(
                onset_envelope=onset_envelope, sr=sr, hop_length=_BEAT_HOP_LENGTH
            )
            tempo_bpm = float(np.atleast_1d(tempo)[0])
            bpm_confidence_value = _bpm_confidence(
                librosa, onset_envelope, sr, _BEAT_HOP_LENGTH, tempo_bpm
            )
            # beat_frames is the same beat grid beat_track derived tempo_bpm
            # from -- reused directly, not a second onset/beat-tracking pass.
            beat_grid, downbeat_grid, phrase_boundaries = _beat_grids(
                librosa, beat_frames, sr, _BEAT_HOP_LENGTH
            )
            chroma = librosa.feature.chroma_cqt(y=waveform, sr=sr, hop_length=_CHROMA_HOP_LENGTH)
            frames_per_second = sr / _CHROMA_HOP_LENGTH
            musical_key, key_mode, key_confidence_value = _estimate_key(chroma)
            start_second, end_second, method = _best_segment(
                chroma, frames_per_second, duration_seconds
            )
            loudness_lufs = _integrated_loudness_lufs(waveform, sr, catalog_track_id)
        except Exception as exc:
            # librosa/audioread/soundfile raise a wide, backend-dependent
            # exception surface for unreadable audio; analysis degrading to
            # "failed" (SegmentSelector then uses the whole clip) is the
            # correct behavior for any of them, so this is deliberately broad.
            logger.warning("Catalog track %s analysis failed: %s", catalog_track_id, exc)
            row.analysis_status = "failed"
            db.commit()
            return

        row.bpm = round(tempo_bpm, 2)
        row.bpm_confidence = round(bpm_confidence_value, 4)
        row.musical_key = musical_key
        row.key_mode = key_mode
        row.camelot = camelot_for(musical_key, key_mode)
        row.key_confidence = round(key_confidence_value, 4)
        row.integrated_loudness_lufs = loudness_lufs
        row.beat_grid_json = beat_grid
        row.downbeat_grid_json = downbeat_grid
        row.phrase_boundaries_json = phrase_boundaries
        row.segment_start_second = start_second
        row.segment_end_second = end_second
        row.segment_method = method
        row.analysis_status = "completed"
        row.analysis_version = ANALYSIS_VERSION
        row.analyzed_at = utc_now()
        db.commit()


def requeue_pending_analysis() -> int:
    """Called once at app startup (see main.py's lifespan): re-dispatches
    analysis for every catalog_tracks row still analysis_status='pending'.

    UploadQueue's own job durability (see upload_queue.py's module
    docstring) covers the upload/storage step, but the *analysis* dispatch
    that follows it -- submit_analysis's queue entry -- is a plain
    in-process PriorityQueue with no persistence of its own. If the process
    crashes or restarts between "analysis job queued" and "job completed,"
    that queued work simply disappears and the row is stranded at
    "pending" with nothing left to ever finish it.

    Safe to requeue unconditionally, no "is this actually still running
    somewhere" check needed: analysis_status is written exactly twice in
    this whole codebase, both in analyze_catalog_track's own two terminal
    branches (a single "failed" commit on exception, a single "completed"
    commit at the very end of a successful run) -- there is no
    intermediate "processing"/"analyzing" status a crash could have left a
    row in. "pending" always means "never finished," never "might be
    mid-flight elsewhere."
    """

    with db_module.SessionLocal() as db:
        pending_ids = [
            row_id
            for (row_id,) in db.query(CatalogTrack.id)
            .filter(CatalogTrack.analysis_status == "pending")
            .all()
        ]

    requeued = 0
    for track_id in pending_ids:
        try:
            upload_queue.upload_queue.submit_analysis(track_id)
        except Full:
            logger.warning(
                "audio_analysis: queue full while requeuing pending catalog track %s at startup; "
                "stays pending",
                track_id,
            )
            continue
        requeued += 1

    if requeued:
        logger.warning(
            "audio_analysis: requeued %d catalog track(s) still analysis_status='pending' at startup",
            requeued,
        )
    return requeued
