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
from app.schemas import SelectedSegment, Track
from app.services.pipeline.interfaces import SegmentSelector

# Used only when duration is unknown (e.g. an Audius track that reported 0).
FALLBACK_SEGMENT_SECONDS = 40


class LibrosaSegmentSelector(SegmentSelector):
    def select(self, db: Session, track: Track) -> SelectedSegment:
        if track.catalog_track_id is not None:
            row = (
                db.query(CatalogTrack)
                .filter(CatalogTrack.id == track.catalog_track_id)
                .first()
            )
            if (
                row is not None
                and row.analysis_status in ("completed", "not_applicable")
                and row.segment_start_second is not None
                and row.segment_end_second is not None
            ):
                return SelectedSegment(
                    track=track,
                    start_second=row.segment_start_second,
                    end_second=row.segment_end_second,
                    method=row.segment_method or "whole_clip",
                    bpm=row.bpm,
                    musical_key=row.musical_key,
                )

        end_second = track.duration_seconds if track.duration_seconds > 0 else FALLBACK_SEGMENT_SECONDS
        return SelectedSegment(
            track=track,
            start_second=0,
            end_second=end_second,
            method="whole_clip",
            bpm=None,
            musical_key=None,
        )
