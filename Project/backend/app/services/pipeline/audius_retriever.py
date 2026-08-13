"""CandidateRetriever wrapping the existing Audius lookup.

Maps audius_service.search_tracks' dicts into the same Track shape the
catalog retriever returns, so both are interchangeable behind one interface.
"""

from sqlalchemy.orm import Session

from app.schemas import PromptIntent, Track
from app.services.audius_service import search_tracks
from app.services.pipeline.interfaces import CandidateRetriever


class AudiusCandidateRetriever(CandidateRetriever):
    name = "audius"

    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
        # Audius already does full-text search across its own catalog, so a
        # named artist is just forwarded as the query rather than fuzzy
        # matched client-side.
        query = intent.artist or intent.search_query
        raw_tracks = search_tracks(query, limit=limit)
        tracks: list[Track] = []
        for item in raw_tracks:
            if not isinstance(item, dict):
                continue
            audio_url = item.get("audio_url")
            source_track_id = item.get("source_track_id")
            if not isinstance(audio_url, str) or not audio_url.strip():
                continue
            if not isinstance(source_track_id, (str, int)):
                continue
            try:
                duration = max(0, int(item.get("duration") or 0))
            except (TypeError, ValueError):
                duration = 0
            tracks.append(
                Track(
                    source="audius",
                    source_track_id=str(source_track_id),
                    title=str(item.get("title") or "Unknown title")[:255],
                    artist=str(item.get("artist") or "Unknown artist")[:255],
                    album=None,
                    audio_url=audio_url,
                    cover_url=item.get("cover_url") if isinstance(item.get("cover_url"), str) else None,
                    duration_seconds=duration,
                    genre=item.get("genre") if isinstance(item.get("genre"), str) else None,
                    vibe=item.get("mood") if isinstance(item.get("mood"), str) else None,
                    vibe_label=None,
                    catalog_track_id=None,
                    local_path=None,
                )
            )
        return tracks
