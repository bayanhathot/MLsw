"""SegmentSelector reading the librosa self-similarity analysis that already
ran as a one-time upload_queue job (see audio_analysis.py).

For a Track backed by a local file whose analysis has completed, this reads
the cached chorus/hook window. For anything without a completed local
analysis -- an Audius preview, or a catalog upload still queued/failed -- the
whole clip is the selection, per requirement 5.

"completed" and "not_applicable" both mean "trust segment_start/end as
authoritative" -- "failed"/"pending" don't, since a failed *re*-analysis
attempt can leave stale segment_start/end sitting from a previous
successful run (analyze_catalog_track only ever sets analysis_status
without touching segment fields on failure). "not_applicable" is the
bundled 4-track demo catalog specifically (catalog_retriever._SEED_TRACKS):
never analyzed by librosa at all, but their segment_start/end were chosen
deliberately at seed time, not left over from anything -- excluding them
here would silently widen their playback window to the whole clip instead
of the intended 45s loop.
"""

import logging

from sqlalchemy.orm import Session

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.schemas import SelectedSegment, Track
from app.services.pipeline.interfaces import SegmentSelector

logger = logging.getLogger(__name__)

# Used only when duration is unknown (e.g. an Audius track that reported 0).
FALLBACK_SEGMENT_SECONDS = 40

# Absolute dBFS floor for the whole-clip fallback's head/tail silence scan.
# Deliberately absolute (not relative to the track's own peak, unlike
# audio_analysis._SILENCE_FLOOR_DBFS): this is pydub's own silence
# detector, run over the raw clip at session time, not the analysis
# pipeline's own peak-normalized measurement -- pydub's own documented
# default for detect_leading_silence is also -50 dBFS.
_TRIM_SILENCE_THRESHOLD_DBFS = -50.0
_MIN_TRIMMED_WINDOW_SECONDS = 1


def _trim_leading_trailing_silence(local_path: str, start_second: int, end_second: int) -> tuple[int, int]:
    """Cheap head/tail silence trim for a local file's whole-clip fallback
    window (requirement 3: a silent lead-in/outro must not play as the
    whole "segment") -- a pydub-only chunk scan, deliberately no librosa
    import: this runs at session time, not analysis time, so it must stay
    fast and bounded. Reuses audio_renderer's own _bounded()/
    LOCAL_AUDIO_OP_TIMEOUT_SECONDS wrapper -- the same protection every
    other session-time local-file decode in this codebase already gets
    (see audio_renderer._load_clip) -- so a slow/stuck decode can't hang
    the live session-resolution request the way an unbounded
    AudioSegment.from_file/librosa.load call could.

    Any failure (timeout, corrupt/unreadable file) falls back to the
    untrimmed (start_second, end_second) window unchanged -- exactly
    today's pre-fix behavior -- rather than raising into the live
    session-resolution path."""

    # Imported lazily and from here (not module level): keeps this module
    # free of a hard import-time dependency on audio_renderer, and pydub
    # itself is only needed on this specific fallback path.
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence

    from app.services.pipeline import audio_renderer

    try:
        clip = audio_renderer._bounded(
            lambda: AudioSegment.from_file(local_path),
            timeout_seconds=audio_renderer.LOCAL_AUDIO_OP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("Whole-clip silence trim skipped for %s: %s", local_path, exc)
        return start_second, end_second
    if clip is None or len(clip) == 0:
        return start_second, end_second

    leading_ms = detect_leading_silence(clip, silence_threshold=_TRIM_SILENCE_THRESHOLD_DBFS)
    trailing_ms = detect_leading_silence(clip.reverse(), silence_threshold=_TRIM_SILENCE_THRESHOLD_DBFS)
    trimmed_start = start_second + leading_ms // 1000
    trimmed_end = end_second - trailing_ms // 1000
    if trimmed_end - trimmed_start < _MIN_TRIMMED_WINDOW_SECONDS:
        # Trimmed to nothing (a fully/near-silent clip) -- keep the
        # original untrimmed window rather than a zero/negative one. A
        # genuinely silent catalog upload is rejected at upload time (see
        # upload_queue._validate_decodable_audio); this trim only tightens
        # a real clip's dead air, it isn't the last line of defense
        # against silence.
        return start_second, end_second
    return trimmed_start, trimmed_end


def _segment_from_analysis_row(track: Track, row) -> SelectedSegment | None:
    """Shared by both the CatalogTrack and ExternalTrack branches below --
    both tables carry identically-shaped analysis columns (see
    external_track.py's own docstring for why), so one function builds a
    SelectedSegment from either kind of row. None when the row isn't
    trustworthy yet (see each branch's own analysis_status/is_stale
    check) -- the caller falls through to the whole-clip default."""

    if row is None or row.segment_start_second is None or row.segment_end_second is None:
        return None
    return SelectedSegment(
        track=track,
        start_second=row.segment_start_second,
        end_second=row.segment_end_second,
        method=row.segment_method or "whole_clip",
        bpm=row.bpm,
        bpm_confidence=row.bpm_confidence,
        musical_key=row.musical_key,
        key_mode=row.key_mode,
        camelot=row.camelot,
        key_confidence=row.key_confidence,
        phrase_boundaries=row.phrase_boundaries_json,
        integrated_loudness_lufs=row.integrated_loudness_lufs,
    )


class LibrosaSegmentSelector(SegmentSelector):
    def select(self, db: Session, track: Track) -> SelectedSegment:
        if track.catalog_track_id is not None:
            row = (
                db.query(CatalogTrack)
                .filter(CatalogTrack.id == track.catalog_track_id)
                .first()
            )
            if row is not None and row.analysis_status in ("completed", "not_applicable"):
                segment = _segment_from_analysis_row(track, row)
                if segment is not None:
                    return segment

        # Mirrors the catalog branch above exactly (Prompt 5 step 1's own
        # requirement: an enriched external Track behaves identically to a
        # catalog Track from here downward) -- the one extra condition,
        # `not row.is_stale`, has no catalog_tracks equivalent: a
        # fingerprint mismatch (pipeline.external_track_cache.
        # verify_fingerprint) flips this without touching analysis_status
        # itself, specifically so this check alone is enough to stop
        # trusting a row's segment/DSP fields the moment they're known
        # out of date, without waiting for re-analysis to overwrite them.
        elif track.external_track_id is not None:
            row = (
                db.query(ExternalTrack)
                .filter(ExternalTrack.id == track.external_track_id)
                .first()
            )
            if row is not None and row.analysis_status == "completed" and not row.is_stale:
                segment = _segment_from_analysis_row(track, row)
                if segment is not None:
                    return segment

        # Whole-clip fallback (no completed analysis to trust): trim
        # leading/trailing silence when a local file is actually available
        # to scan (a catalog track, whether never-analyzed, still queued,
        # or failed) -- an Audius track's audio isn't on disk at this
        # point (only fetched during the actual render step, under its own
        # timeout, never here), so track.local_path is None and this stays
        # exactly today's untrimmed behavior for that case.
        start_second = 0
        end_second = track.duration_seconds if track.duration_seconds > 0 else FALLBACK_SEGMENT_SECONDS
        if track.local_path:
            start_second, end_second = _trim_leading_trailing_silence(
                track.local_path, start_second, end_second
            )

        return SelectedSegment(
            track=track,
            start_second=start_second,
            end_second=end_second,
            method="whole_clip",
            bpm=None,
            bpm_confidence=None,
            musical_key=None,
            key_mode=None,
            camelot=None,
            key_confidence=None,
            phrase_boundaries=None,
            integrated_loudness_lufs=None,
        )
