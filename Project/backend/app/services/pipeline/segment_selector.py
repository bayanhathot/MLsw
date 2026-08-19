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

from sqlalchemy.orm import Session

from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.schemas import SelectedSegment, Track
from app.services.pipeline.interfaces import SegmentSelector

# Used only when duration is unknown (e.g. an Audius track that reported 0).
FALLBACK_SEGMENT_SECONDS = 40


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

        end_second = track.duration_seconds if track.duration_seconds > 0 else FALLBACK_SEGMENT_SECONDS
        return SelectedSegment(
            track=track,
            start_second=0,
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
