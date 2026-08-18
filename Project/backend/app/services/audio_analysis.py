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
picked. Key detection is a simple strongest-average-chroma-bin heuristic.
Both are deterministic signal-processing, not a trained model.
"""

import logging

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
# this is meant to support. "v1" is the chroma+beat_track+self-similarity
# approach implemented in this file today.
ANALYSIS_VERSION = "v1"

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Bounds CPU/memory for a pathologically long upload; analysis only needs
# enough of the track to find one representative ~30s window.
_MAX_ANALYSIS_SECONDS = 240
_TARGET_SEGMENT_SECONDS = 30
_CHROMA_HOP_LENGTH = 512


def _estimate_key(chroma: np.ndarray) -> str:
    return _PITCH_CLASSES[int(np.argmax(chroma.mean(axis=1)))]


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
            tempo, _ = librosa.beat.beat_track(y=waveform, sr=sr)
            chroma = librosa.feature.chroma_cqt(y=waveform, sr=sr, hop_length=_CHROMA_HOP_LENGTH)
            frames_per_second = sr / _CHROMA_HOP_LENGTH
            musical_key = _estimate_key(chroma)
            start_second, end_second, method = _best_segment(
                chroma, frames_per_second, duration_seconds
            )
        except Exception as exc:
            # librosa/audioread/soundfile raise a wide, backend-dependent
            # exception surface for unreadable audio; analysis degrading to
            # "failed" (SegmentSelector then uses the whole clip) is the
            # correct behavior for any of them, so this is deliberately broad.
            logger.warning("Catalog track %s analysis failed: %s", catalog_track_id, exc)
            row.analysis_status = "failed"
            db.commit()
            return

        row.bpm = round(float(np.atleast_1d(tempo)[0]), 2)
        row.musical_key = musical_key
        row.segment_start_second = start_second
        row.segment_end_second = end_second
        row.segment_method = method
        row.analysis_status = "completed"
        row.analysis_version = ANALYSIS_VERSION
        row.analyzed_at = utc_now()
        db.commit()
