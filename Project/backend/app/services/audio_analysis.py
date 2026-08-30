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
of track length), and among candidate windows that clear both the relative
_SILENCE_FLOOR_DBFS and absolute _ABSOLUTE_SILENCE_FLOOR_DBFS
(see _rank_windows), the one with the highest average similarity to the
rest of the track -- i.e. the most repeated/representative section -- is
picked. The energy floor exists because self-similarity alone discards
amplitude entirely: a silent or near-silent passage can be maximally
"self-similar" to itself and would otherwise win outright -- the course
rubric's own worked example of a hallucinated recommendation ("choosing a
part of a song that is silence"). A track that's too short to window falls
back to "whole_clip"; one long enough to window but where *no* window
clears the floor is a distinct sentinel analyze_audio() turns into a raised
exception (see _best_segment's own docstring) rather than ever reporting a
uniformly near-silent track's whole duration as a completed analysis.
Ranking only ever runs within one contiguous decoded chunk -- for a track
longer than _MAX_ANALYSIS_SECONDS, _select_long_track_segment ranks the
initial prefix chunk against several more sampled from the rest of the
track's real duration and keeps whichever chunk's own best window scores
highest, rather than only ever considering the first _MAX_ANALYSIS_SECONDS
(see that function's own docstring). Key detection is
real Krumhansl-Schmuckler-style key-finding: the mean chroma profile is
correlated against 24 rotated major/minor key-profile templates and the
best-correlating (root, mode) pair wins -- see _estimate_key. Beat-grid
timing (beat_grid/downbeat_grid/phrase_boundaries) is derived from
librosa.beat.beat_track's own beat-frame output -- already computed to
derive bpm, never a second onset-detection pass; only the beat grid itself
is genuine data, downbeat_grid/phrase_boundaries are a coarse fixed-meter
heuristic layered on top of it, not real meter/structure detection -- see
_beat_grids. All of the above are deterministic signal-processing, not a
trained model.
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from queue import Full

import numpy as np

from app.core.time import utc_now
from app.database import database as db_module
from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.services import upload_queue
from app.services.admin_debug_events import publish_external_track_updated
from app.services.pipeline.catalog_retriever import CATALOG_AUDIO_SUBDIR

logger = logging.getLogger(__name__)

# Prompt 1's own finding, not repeated here: no existing cap/backoff policy
# exists to reuse for catalog_tracks (analyze_catalog_track never
# auto-retries a *failed* row -- only requeue_pending_analysis's
# still-"pending" rows get resubmitted, and only at startup). A small,
# explicit cap is new for external_tracks specifically, matching this
# codebase's general small-bounded-constant style (e.g.
# session_manager.AUDIO_RENDER_RETRY_LIMIT) rather than an invented
# *second* policy parallel to a real existing one.
EXTERNAL_ANALYSIS_MAX_ATTEMPTS = int(os.getenv("EXTERNAL_ANALYSIS_MAX_ATTEMPTS", "3"))

# Bump this whenever the analysis approach below changes (a different
# chroma/beat-tracking method, a different segment-selection heuristic,
# etc.) so existing rows can be targeted for reprocessing by version later
# -- see CatalogTrack.analysis_version's own docstring for the query shape
# this is meant to support. "v4" keeps CQT chroma as the normal path but
# falls back to STFT chroma when a valid low-sample-rate file cannot support
# CQT's requested frequency range. "v3" added an absolute dBFS floor to
# segment selection; v2 introduced real Krumhansl-Schmuckler key-finding;
# v1 used a bare strongest-average-chroma-bin heuristic.
ANALYSIS_VERSION = "v4"

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Any candidate window whose mean level falls below this, relative to the
# track's own peak sample amplitude, is disqualified from
# chorus_detection selection outright -- self-similarity alone (see
# _bucket_chroma) discards amplitude entirely, so a silent or near-silent
# passage can otherwise "win" by being uniformly (and meaninglessly)
# self-similar. Deliberately relative to the track's own peak, not a
# fixed absolute level: a quietly-mastered track's real highlight should
# still be selectable, and a loudly-mastered track's near-silent passages
# should still be rejected, regardless of the track's own overall level.
# This is the fix for the course rubric's own worked hallucination
# example: "choosing a part of a song that is silence."
_SILENCE_FLOOR_DBFS = -45.0
# D8: the relative floor above distinguishes a real highlight from a quiet
# passage inside the same track, but cannot identify a uniformly quiet track:
# -60 dBFS noise is only a few dB below its *own* tiny peak. Every candidate
# must therefore also clear this absolute full-scale floor. Keeping the two
# checks separate preserves quietly mastered real music while preventing an
# entire near-silent provider track from being labeled chorus_detection.
_ABSOLUTE_SILENCE_FLOOR_DBFS = -50.0

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
# Bounds CPU/memory for bpm/key/beat-grid detection (none of which need
# full-track coverage) and is the prefix analyze_audio() always decodes
# first. D3: segment/highlight selection is no longer capped to just this
# prefix -- a track longer than this gets _select_long_track_segment's
# additional bounded sampling across the rest of its real duration, so the
# most representative ~30s window can still be found well past this mark
# in an 8-20 minute Emotional/Tarab track (see that function's own
# docstring for the follow-on budget).
_MAX_ANALYSIS_SECONDS = 600
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


def _bucket_rms_dbfs(
    rms_frames: np.ndarray, frames_per_second: float, n_buckets: int, reference_amplitude: float
) -> np.ndarray:
    """Per-second mean level relative to ``reference_amplitude`` -- either
    the track peak for within-track contrast or 1.0 for absolute dBFS.
    Bucketed at the same rate/hop length
    _bucket_chroma uses so the two arrays line up index-for-index (padded
    with the last real frame if librosa's own frame-counting for RMS vs.
    chroma_cqt differs by a frame or two at the same hop_length, so a
    short mismatch never desyncs the two bucket arrays). -inf for every
    bucket when the reference is non-positive,
    rather than a divide-by-zero."""

    bucket_frames = max(1, int(round(frames_per_second)))
    needed = n_buckets * bucket_frames
    if rms_frames.shape[0] < needed:
        rms_frames = np.pad(rms_frames, (0, needed - rms_frames.shape[0]), mode="edge")
    trimmed = rms_frames[:needed]
    bucket_rms = trimmed.reshape(n_buckets, bucket_frames).mean(axis=1)
    if reference_amplitude <= 0.0:
        return np.full(n_buckets, -np.inf)
    with np.errstate(divide="ignore"):
        return 20.0 * np.log10(np.maximum(bucket_rms, 1e-12) / reference_amplitude)


def _rank_windows(
    chroma: np.ndarray,
    frames_per_second: float,
    rms_frames: np.ndarray,
    peak_amplitude: float,
) -> tuple[int, int, float, float | None] | None:
    """The self-similarity + energy-floor window ranking core, shared by
    _best_segment (a track fully covered by one decoded chunk) and D3's
    _select_long_track_segment below (a track longer than
    _MAX_ANALYSIS_SECONDS, ranked across several chunks spread over its
    full real duration instead of just the first _MAX_ANALYSIS_SECONDS).

    Self-similarity ranking (see _bucket_chroma) discards amplitude
    entirely -- a silent or near-silent window can be maximally
    "self-similar" to itself and win on that basis alone. The relative
    _SILENCE_FLOOR_DBFS disqualifies windows far below the track's own peak;
    _ABSOLUTE_SILENCE_FLOOR_DBFS also rejects a uniformly quiet track whose
    own peak is tiny. Among windows that pass both, the existing similarity
    ranking is unchanged.

    Returns None if there are too few buckets to window at all (the
    legitimate too-short-to-window case). Otherwise
    (local_start_second, local_end_second, score, level_dbfs) for the
    best-scoring window that clears the floor, or (0, total_seconds, -1.0,
    None) if every window here falls below it (D2/Cause B) -- callers
    branch on the `level` field's own None-ness to tell those two non-None
    cases apart, rather than a sentinel score a disqualified window's own
    score could still exceed, which would silently mislabel start=0 (the
    loop's untouched initial value) as a real winner."""

    buckets = _bucket_chroma(chroma, frames_per_second)
    total_seconds = buckets.shape[1]
    window = min(total_seconds, _TARGET_SEGMENT_SECONDS)
    if total_seconds <= window or window <= 0:
        return None

    relative_level_db = _bucket_rms_dbfs(
        rms_frames, frames_per_second, total_seconds, peak_amplitude
    )
    absolute_level_dbfs = _bucket_rms_dbfs(
        rms_frames, frames_per_second, total_seconds, 1.0
    )

    norms = buckets / (np.linalg.norm(buckets, axis=0, keepdims=True) + 1e-9)
    similarity = norms.T @ norms  # second-by-second cosine self-similarity

    best_start, best_score, best_level = 0, -1.0, None
    for start in range(0, total_seconds - window + 1):
        window_relative_level = float(relative_level_db[start : start + window].mean())
        window_absolute_level = float(absolute_level_dbfs[start : start + window].mean())
        if (
            window_relative_level < _SILENCE_FLOOR_DBFS
            or window_absolute_level < _ABSOLUTE_SILENCE_FLOOR_DBFS
        ):
            continue  # disqualified: too quiet to be a real "highlight"
        score = float(similarity[start : start + window, :].mean())
        if score > best_score:
            # Persist/report the absolute value: unlike a track-relative
            # number, it is meaningful evidence that this window is audible.
            best_score, best_start, best_level = score, start, window_absolute_level

    if best_level is None:
        return 0, total_seconds, best_score, None
    return best_start, best_start + window, best_score, best_level


def _best_segment(
    chroma: np.ndarray,
    frames_per_second: float,
    duration_seconds: float,
    rms_frames: np.ndarray,
    peak_amplitude: float,
) -> tuple[int, int, str, float | None]:
    """Returns (start_second, end_second, method, segment_level_dbfs) --
    the fourth field is the winning window's own measured level (None for
    a whole_clip/all-below-floor result, where no single window was
    scored), persisted so it can be shown as evidence that the selected
    segment isn't silence (see scripts/eval_hallucination_robustness.py).
    A thin wrapper around _rank_windows -- see that function's own
    docstring for the actual ranking logic."""

    result = _rank_windows(chroma, frames_per_second, rms_frames, peak_amplitude)
    if result is None:
        return 0, max(1, int(duration_seconds)), "whole_clip", None
    start, end, _score, level = result
    if level is None:
        # D2/Cause B: every candidate window was below the silence floor --
        # unlike the too-short-to-window case above (a legitimate reason to
        # trust the whole clip), this means nothing in the analyzed portion
        # ever had a real, sustained loud passage. Returning "whole_clip"
        # here would be indistinguishable from that legitimate case and
        # would report a uniformly near-silent track's entire (possibly
        # minutes-long) duration as a *completed* analysis -- exactly the
        # course rubric's hallucination example, just moved up from segment
        # selection to the analysis result itself. This sentinel method
        # value is never persisted: analyze_audio() below intercepts it
        # immediately and raises instead of building an AnalysisResult, so
        # both callers' existing except-branches turn it into an ordinary
        # "failed" analysis_status (same retry/fallback machinery every
        # other analysis failure already uses) rather than this needing a
        # third, DB-persisted segment_method value.
        return 0, max(1, int(duration_seconds)), "all_windows_below_silence_floor", None
    return start, end, "chorus_detection", level


# D3: how many additional chunks a track longer than _MAX_ANALYSIS_SECONDS
# gets sampled from, spread evenly across whatever's past
# analyze_audio()'s own prefix load (needed regardless, for bpm/key/
# beat-grid, which don't need full-track coverage the way a highlight
# does), so an 8-20 minute Emotional/Tarab track's real highlight can be
# found anywhere in it. Each chunk is long enough to contain several full
# _TARGET_SEGMENT_SECONDS candidate windows (self-similarity needs more
# than one to actually rank anything); the total across every chunk
# (_LONG_TRACK_REMAINDER_CHUNKS * _LONG_TRACK_REMAINDER_CHUNK_SECONDS =
# 300s) is additive to the existing _MAX_ANALYSIS_SECONDS prefix, not a
# second one of the same size -- still bounded (never scales with however
# long the track actually is), just not literally the same 600s ceiling.
_LONG_TRACK_REMAINDER_CHUNKS = 4
_LONG_TRACK_REMAINDER_CHUNK_SECONDS = 75


def _extract_chroma(librosa_module, waveform: np.ndarray, sr: float) -> np.ndarray:
    """Extract twelve-bin chroma without rejecting valid low-rate audio.

    CQT is the preferred representation used by the existing analysis. At
    low sample rates, librosa can reject it because its highest CQT basis
    frequency exceeds the signal's Nyquist frequency. That is a limitation
    of this feature extractor, not evidence that the uploaded audio is
    invalid, so only that specific error falls back to STFT chroma. Every
    other ParameterError still propagates to the normal failed-analysis
    path instead of being hidden.
    """

    try:
        return librosa_module.feature.chroma_cqt(
            y=waveform, sr=sr, hop_length=_CHROMA_HOP_LENGTH
        )
    except librosa_module.util.exceptions.ParameterError as exc:
        if "nyquist" not in str(exc).lower():
            raise
        logger.info(
            "CQT chroma is unavailable at sample rate %s; using STFT chroma",
            sr,
        )
        return librosa_module.feature.chroma_stft(
            y=waveform, sr=sr, hop_length=_CHROMA_HOP_LENGTH
        )


def _select_long_track_segment(
    librosa_module,
    path: str,
    true_duration_seconds: float,
    prefix_chroma: np.ndarray,
    prefix_frames_per_second: float,
    prefix_rms_frames: np.ndarray,
    prefix_peak_amplitude: float,
    duration_seconds: float,
) -> tuple[int, int, str, float | None]:
    """D3: extends segment selection past analyze_audio()'s own prefix
    (already decoded/scored by the caller -- chroma/rms/peak for the first
    _MAX_ANALYSIS_SECONDS) by additionally sampling
    _LONG_TRACK_REMAINDER_CHUNKS chunks spread across the rest of the
    track's real duration. Ranks the prefix's own candidate window against
    every remainder chunk's own candidate window -- each ranked
    independently within its own contiguous chunk, since self-similarity
    across a temporal gap between two non-contiguous chunks isn't
    meaningful -- and returns whichever scores highest, with real absolute
    timestamps (a remainder chunk's local window offset by its own real
    start-of-chunk second). Every chunk (prefix included) is judged against
    one shared peak amplitude -- the loudest sample found across the
    *whole* sampled set, not just its own chunk -- so the energy floor
    stays genuinely relative to the track's real peak even when that peak
    turns out to sit in a remainder chunk analyze_audio()'s own prefix
    never saw."""

    remainder_start = _MAX_ANALYSIS_SECONDS
    remainder_span = true_duration_seconds - remainder_start
    if remainder_span > _LONG_TRACK_REMAINDER_CHUNK_SECONDS:
        max_offset = remainder_start + remainder_span - _LONG_TRACK_REMAINDER_CHUNK_SECONDS
        if _LONG_TRACK_REMAINDER_CHUNKS == 1:
            offsets = [remainder_start]
        else:
            step = (max_offset - remainder_start) / (_LONG_TRACK_REMAINDER_CHUNKS - 1)
            offsets = [remainder_start + i * step for i in range(_LONG_TRACK_REMAINDER_CHUNKS)]
    elif remainder_span > 0:
        offsets = [remainder_start]
    else:
        offsets = []

    chunks = []  # (offset, chroma, frames_per_second, rms_frames)
    overall_peak = prefix_peak_amplitude
    for offset in offsets:
        waveform, sr = librosa_module.load(
            path, sr=None, mono=True, offset=offset, duration=_LONG_TRACK_REMAINDER_CHUNK_SECONDS,
        )
        if waveform.size == 0:
            continue
        chroma = _extract_chroma(librosa_module, waveform, sr)
        frames_per_second = sr / _CHROMA_HOP_LENGTH
        rms_frames = librosa_module.feature.rms(y=waveform, hop_length=_CHROMA_HOP_LENGTH)[0]
        overall_peak = max(overall_peak, float(np.max(np.abs(waveform))))
        chunks.append((offset, chroma, frames_per_second, rms_frames))

    candidates: list[tuple[float, int, int, float]] = []  # (score, real_start, real_end, level)
    any_windowable = False

    prefix_result = _rank_windows(prefix_chroma, prefix_frames_per_second, prefix_rms_frames, overall_peak)
    if prefix_result is not None:
        any_windowable = True
        local_start, local_end, score, level = prefix_result
        if level is not None:
            candidates.append((score, local_start, local_end, level))

    for offset, chroma, frames_per_second, rms_frames in chunks:
        result = _rank_windows(chroma, frames_per_second, rms_frames, overall_peak)
        if result is None:
            continue
        any_windowable = True
        local_start, local_end, score, level = result
        if level is None:
            continue
        candidates.append((score, int(offset) + local_start, int(offset) + local_end, level))

    if not candidates:
        if any_windowable:
            # D2/Cause B, same reasoning as _best_segment's own docstring --
            # a sentinel analyze_audio() intercepts and raises on, never
            # persisted.
            return 0, max(1, int(true_duration_seconds)), "all_windows_below_silence_floor", None
        return 0, max(1, int(duration_seconds)), "whole_clip", None

    best_score, best_start, best_end, best_level = max(candidates, key=lambda candidate: candidate[0])
    return best_start, best_end, "chorus_detection", best_level


def _integrated_loudness_lufs(waveform: np.ndarray, sr: float, label: str) -> float | None:
    """ITU-R BS.1770 integrated loudness of the already-loaded waveform, via
    pyloudnorm -- measured once here over the whole (up to
    _MAX_ANALYSIS_SECONDS) analyzed clip, never re-measured per segment or
    per crossfade at render time (see CatalogTrack.integrated_loudness_lufs'
    own docstring for why; audio_renderer.py just applies a flat gain
    derived from this stored value instead). Kept in its own try/except,
    separate from analyze_audio's own -- a loudness-measurement failure
    (e.g. BS.1770's gating finds no audio above the -70 LUFS absolute
    threshold, on a near-silent clip) must not invalidate the bpm/key/
    segment results that succeeded independently of it. None on any
    failure or non-finite result, matching this pipeline's established
    missing-signal handling (see this column's docstring). `label` is a
    free-form string for the warning log only (e.g. "catalog track 5" or
    "external track 12") -- analyze_audio() is shared by both adapters and
    has no opinion on which kind of row is being analyzed."""

    try:
        import pyloudnorm

        meter = pyloudnorm.Meter(int(sr))
        loudness = meter.integrated_loudness(waveform)
    except Exception as exc:
        logger.warning("Loudness measurement failed for %s: %s", label, exc)
        return None
    return round(loudness, 2) if np.isfinite(loudness) else None


@dataclass
class AnalysisResult:
    """Everything one run of analyze_audio() produces -- already rounded to
    the exact precision each field was stored at before this refactor, so
    both adapters (analyze_catalog_track/analyze_external_track) can just
    assign these straight onto their own row without re-deriving anything."""

    bpm: float
    bpm_confidence: float
    musical_key: str
    key_mode: str
    camelot: str | None
    key_confidence: float
    integrated_loudness_lufs: float | None
    beat_grid: list[float]
    downbeat_grid: list[float]
    phrase_boundaries: list[float]
    segment_start_second: int
    segment_end_second: int
    segment_method: str
    # The selected window's own measured level (dBFS, relative to the
    # full-scale amplitude) -- None for a whole_clip result, where
    # no single window was scored against _SILENCE_FLOOR_DBFS. Not a
    # persisted DB column (no schema change): _apply_result deliberately
    # doesn't copy this onto CatalogTrack/ExternalTrack, since its only
    # consumer is scripts/eval_hallucination_robustness.py, which calls
    # analyze_audio() directly and reads it straight off this dataclass as
    # evidence the selected segment isn't silence.
    segment_level_dbfs: float | None


def analyze_audio(path: str, *, label: str) -> AnalysisResult:
    """The one shared DSP core (Prompt 2) -- every one-time Cuemix audio
    analysis, whether the source was a local catalog upload
    (analyze_catalog_track) or a temporarily-fetched Audius track
    (analyze_external_track), funnels through this single function. There
    is exactly one DSP implementation; the two callers differ only in
    where the audio file came from and which table's row they persist the
    result onto.

    Raises on any failure -- librosa/audioread/soundfile raise a wide,
    backend-dependent exception surface for unreadable audio, and this
    function has no row of its own to mark "failed"; each caller wraps
    this call in its own try/except and decides what failure means for
    its own table (catalog_tracks vs. external_tracks have different
    retry/attempt-count bookkeeping -- see ExternalTrack.analysis_attempt_count's
    own docstring for why they can't share one policy)."""

    # Imported lazily: librosa pulls in a heavy dependency tree (numpy/scipy/
    # numba/soundfile) that only the analysis job needs, not every process
    # that imports app.services.audio_analysis.
    import librosa

    waveform, sr = librosa.load(path, sr=None, mono=True, duration=_MAX_ANALYSIS_SECONDS)
    duration_seconds = librosa.get_duration(y=waveform, sr=sr)
    # Computed explicitly (rather than passing y= straight to beat_track)
    # only so _bpm_confidence can read the same onset-strength signal
    # beat_track uses internally to choose its tempo -- otherwise
    # identical to beat_track(y=waveform, sr=sr)'s own default behavior
    # (aggregate=np.median, hop_length=512), so the tempo output itself is
    # unchanged.
    onset_envelope = librosa.onset.onset_strength(
        y=waveform, sr=sr, hop_length=_BEAT_HOP_LENGTH, aggregate=np.median
    )
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope, sr=sr, hop_length=_BEAT_HOP_LENGTH
    )
    tempo_bpm = float(np.atleast_1d(tempo)[0])
    bpm_confidence_value = _bpm_confidence(librosa, onset_envelope, sr, _BEAT_HOP_LENGTH, tempo_bpm)
    # beat_frames is the same beat grid beat_track derived tempo_bpm from --
    # reused directly, not a second onset/beat-tracking pass.
    beat_grid, downbeat_grid, phrase_boundaries = _beat_grids(librosa, beat_frames, sr, _BEAT_HOP_LENGTH)
    chroma = _extract_chroma(librosa, waveform, sr)
    frames_per_second = sr / _CHROMA_HOP_LENGTH
    musical_key, key_mode, key_confidence_value = _estimate_key(chroma)
    # Same hop length as the chroma buckets above, so _bucket_rms_dbfs's
    # per-second buckets line up index-for-index with _bucket_chroma's own
    # -- see _best_segment's own docstring for what this feeds.
    rms_frames = librosa.feature.rms(y=waveform, hop_length=_CHROMA_HOP_LENGTH)[0]
    peak_amplitude = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    start_second, end_second, method, segment_level_dbfs = _best_segment(
        chroma, frames_per_second, duration_seconds, rms_frames, peak_amplitude
    )
    # D3: the load above is capped at _MAX_ANALYSIS_SECONDS (needed
    # regardless, for bpm/key/beat-grid above, which don't need full-track
    # coverage) -- but an 8-20 minute Emotional/Tarab track's real
    # highlight can sit well past that. get_duration(path=...) reads the
    # container's real duration directly, without decoding the rest of the
    # file, so this is cheap even when it turns out short enough that
    # nothing further needs to happen (the common case).
    true_duration_seconds = librosa.get_duration(path=path)
    if true_duration_seconds > _MAX_ANALYSIS_SECONDS:
        start_second, end_second, method, segment_level_dbfs = _select_long_track_segment(
            librosa, path, true_duration_seconds, chroma, frames_per_second, rms_frames,
            peak_amplitude, duration_seconds,
        )
    if method == "all_windows_below_silence_floor":
        # See _best_segment's own docstring: this is a sentinel, never a
        # real segment_method -- raising here (before any AnalysisResult is
        # built, and before the loudness measurement below runs for
        # nothing) is what turns it into an ordinary "failed" analysis in
        # both analyze_catalog_track/analyze_external_track's existing
        # except-branches.
        raise ValueError(
            f"Every analyzed window of {label!r} fell below the silence floor -- "
            "no real, sustained loud passage to report as a completed analysis."
        )
    loudness_lufs = _integrated_loudness_lufs(waveform, sr, label)

    return AnalysisResult(
        bpm=round(tempo_bpm, 2),
        # float(...) before round(): librosa/numpy return numpy.float64
        # scalars here, and round() on a numpy scalar returns another numpy
        # scalar, not a native float -- psycopg2 has no adapter for numpy
        # scalar types and falls back to repr(), which under numpy>=2.0
        # renders as "np.float64(...)" instead of a bare number, breaking
        # the INSERT/UPDATE SQL outright. tempo_bpm above is already float()
        # cast for the same reason; these three weren't, so a numpy.float64
        # was silently reaching the DB layer until this analysis fetch was
        # actually exercised.
        bpm_confidence=round(float(bpm_confidence_value), 4),
        musical_key=musical_key,
        key_mode=key_mode,
        camelot=camelot_for(musical_key, key_mode),
        key_confidence=round(float(key_confidence_value), 4),
        integrated_loudness_lufs=None if loudness_lufs is None else float(loudness_lufs),
        beat_grid=beat_grid,
        downbeat_grid=downbeat_grid,
        phrase_boundaries=phrase_boundaries,
        segment_start_second=start_second,
        segment_end_second=end_second,
        segment_method=method,
        segment_level_dbfs=segment_level_dbfs,
    )


def _apply_result(row, result: AnalysisResult) -> None:
    """Shared field assignment for both CatalogTrack and ExternalTrack rows
    -- both carry identically-named/typed analysis columns (see
    external_track.py's own docstring for why), so one function assigns
    onto either. Does NOT touch analysis_status/analysis_version/
    analyzed_at -- those differ slightly between the two callers (e.g.
    ExternalTrack also clears is_stale), so each adapter sets those
    itself right after calling this."""

    row.bpm = result.bpm
    row.bpm_confidence = result.bpm_confidence
    row.musical_key = result.musical_key
    row.key_mode = result.key_mode
    row.camelot = result.camelot
    row.key_confidence = result.key_confidence
    row.integrated_loudness_lufs = result.integrated_loudness_lufs
    row.beat_grid_json = result.beat_grid
    row.downbeat_grid_json = result.downbeat_grid
    row.phrase_boundaries_json = result.phrase_boundaries
    row.segment_start_second = result.segment_start_second
    row.segment_end_second = result.segment_end_second
    row.segment_method = result.segment_method


def analyze_catalog_track(catalog_track_id: int) -> None:
    with db_module.SessionLocal() as db:
        row = db.query(CatalogTrack).filter(CatalogTrack.id == catalog_track_id).first()
        if row is None:
            return
        path = upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / row.storage_name
        try:
            result = analyze_audio(str(path), label=f"catalog track {catalog_track_id}")
        except Exception as exc:
            # librosa/audioread/soundfile raise a wide, backend-dependent
            # exception surface for unreadable audio; analysis degrading to
            # "failed" (SegmentSelector then uses the whole clip) is the
            # correct behavior for any of them, so this is deliberately broad.
            logger.warning("Catalog track %s analysis failed: %s", catalog_track_id, exc)
            row.analysis_status = "failed"
            db.commit()
            return

        _apply_result(row, result)
        row.analysis_status = "completed"
        row.analysis_version = ANALYSIS_VERSION
        row.analyzed_at = utc_now()
        db.commit()


def analyze_external_track(external_track_id: int) -> None:
    """Prompt 2's second adapter: temporarily fetches an Audius track's
    full audio, runs it through the exact same analyze_audio() core
    analyze_catalog_track uses, persists the result onto its
    external_tracks row, and always deletes the temporary file -- on
    success AND failure (see the try/finally below), so a failed analysis
    never leaves audio sitting on disk.

    No live retrieval/session path calls this directly (see
    pipeline/external_track_cache.py, the only caller, gated behind
    AUDIUS_ANALYSIS_CACHE_ENABLED) -- this function's only job is turning
    an external_track_id into a completed-or-failed analysis, the same
    narrow scope analyze_catalog_track has always had.
    """

    import hashlib

    # Imported lazily, same reasoning as audio_renderer's own import site:
    # this pulls in httpx/pydub-adjacent machinery only an actual analysis
    # run needs, and importing audio_renderer here (rather than at module
    # level) also avoids a session_manager/audio_renderer/audio_analysis
    # import cycle, since audio_renderer never needs to import this module.
    from app.services import audius_service
    from app.services.pipeline import audio_renderer

    with db_module.SessionLocal() as db:
        row = db.query(ExternalTrack).filter(ExternalTrack.id == external_track_id).first()
        if row is None:
            return

        if row.source != "audius":
            # Only Audius exists as a source today (see this table's own
            # docstring) -- reported plainly rather than silently guessing
            # at a fetch strategy for a provider this codebase doesn't
            # actually integrate with yet.
            logger.warning(
                "analyze_external_track: no fetch strategy for source=%r (id=%s)",
                row.source, external_track_id,
            )
            row.analysis_status = "failed"
            row.analysis_attempt_count += 1
            row.analysis_last_failed_at = utc_now()
            db.commit()
            publish_external_track_updated(external_track_id)
            return

        # Reuses audio_renderer._download -- the same bounded, multi-hop-
        # redirect-safe fetch every live playback/render path already uses
        # for Audius audio (see audio_renderer.py's own REMOTE_TIMEOUT_SECONDS/
        # _bounded) -- rather than a second, parallel downloader.
        url = audius_service.audius_stream_url(row.external_id)
        data, reason = audio_renderer._download(url)
        if data is None:
            logger.warning(
                "External track %s temporary fetch failed: %s", external_track_id, reason
            )
            row.analysis_status = "failed"
            row.analysis_attempt_count += 1
            row.analysis_last_failed_at = utc_now()
            db.commit()
            publish_external_track_updated(external_track_id)
            return

        tmp_path: str | None = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(data)
            result = analyze_audio(tmp_path, label=f"external track {external_track_id}")
        except Exception as exc:
            logger.warning("External track %s analysis failed: %s", external_track_id, exc)
            row.analysis_status = "failed"
            row.analysis_attempt_count += 1
            row.analysis_last_failed_at = utc_now()
            db.commit()
            publish_external_track_updated(external_track_id)
            return
        finally:
            # Runs on every exit path -- success, the except above, and any
            # exception this try block didn't anticipate -- so the
            # temporary audio is never left on disk (Prompt 2 step 3's
            # explicit requirement) regardless of how analysis ended.
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)

        _apply_result(row, result)
        row.audio_sha256 = hashlib.sha256(data).hexdigest()
        row.analysis_status = "completed"
        row.analysis_version = ANALYSIS_VERSION
        row.analyzed_at = utc_now()
        row.analysis_attempt_count += 1
        # A fresh, successful analysis always supersedes whatever staleness
        # an earlier fingerprint mismatch flagged (pipeline.
        # external_track_cache.verify_fingerprint) -- the new audio_sha256
        # set just above is, by definition, current again.
        row.is_stale = False
        db.commit()
        publish_external_track_updated(external_track_id)


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


def requeue_pending_external_analysis() -> int:
    """External-track counterpart to requeue_pending_analysis() above --
    same crash/restart gap, same fix. external_tracks rows have no startup
    recovery today: pipeline.external_track_cache.enrich_and_dispatch's own
    Case C deliberately skips re-dispatch for any row already
    analysis_status='pending' (see that module's docstring), so a row
    stranded "pending" by a crash between "job queued" and "job completed"
    is never retried by the normal request-driven path -- nothing else in
    this codebase would ever finish it. Reuses the exact same reasoning
    requeue_pending_analysis documents (analysis_status is only ever
    written at a terminal branch, so "pending" always means "never
    finished," never "might be mid-flight elsewhere").

    A no-op query (zero rows) whenever AUDIUS_ANALYSIS_CACHE_ENABLED is
    False, since no external_tracks row is ever created in that state."""

    from app.services.pipeline.external_track_cache import AUDIUS_ANALYSIS_CACHE_ENABLED

    if not AUDIUS_ANALYSIS_CACHE_ENABLED:
        return 0

    with db_module.SessionLocal() as db:
        pending_ids = [
            row_id
            for (row_id,) in db.query(ExternalTrack.id)
            .filter(ExternalTrack.analysis_status == "pending")
            .all()
        ]

    requeued = 0
    for external_track_id in pending_ids:
        try:
            upload_queue.upload_queue.submit_external_analysis(external_track_id)
        except Full:
            logger.warning(
                "audio_analysis: queue full while requeuing pending external track %s at startup; "
                "stays pending",
                external_track_id,
            )
            continue
        requeued += 1

    if requeued:
        logger.warning(
            "audio_analysis: requeued %d external track(s) still analysis_status='pending' at startup",
            requeued,
        )
    return requeued
