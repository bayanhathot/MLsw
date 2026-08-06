"""
mix_service.py

Business logic for creating a persisted Mix from a prompt.

This intentionally duplicates the small segment-building step already
in routers/mixes.py (the older, frontend-disconnected MVP demo
endpoint). That router is explicitly left untouched - it is its own
"mix plan" stub, documented as future AI work - and a service must not
import from a router. Both call the same audius_service.search_tracks()
underneath, so there is exactly one place that talks to Audius.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models.mix import Mix, MixSegment
from app.services.audius_service import search_tracks


def create_mix(db: Session, creator_id: int, prompt: str) -> Mix:
    """
    Search Audius for the prompt and persist the result as a Mix with
    its ordered MixSegment queue.

    Raises 404 if Audius has no matching tracks.
    """

    tracks = search_tracks(prompt, limit=5)

    if not tracks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No tracks found for this prompt.",
        )

    mix = Mix(creator_id=creator_id, prompt=prompt)
    db.add(mix)
    db.flush()  # assigns mix.id without ending the transaction

    for index, track in enumerate(tracks):
        duration = track.get("duration") or 60

        # Same MVP fake segmentation as routers/mixes.py: one 45-second
        # window per track. Real segmentation is future AI work.
        db.add(
            MixSegment(
                mix_id=mix.id,
                position=index + 1,
                title=track["title"],
                artist=track["artist"],
                audio_url=track["audio_url"],
                cover_url=track.get("cover_url"),
                start_second=0,
                end_second=min(45, duration),
                transition_to_next="crossfade",
                source=track["source"],
                source_track_id=track["source_track_id"],
            )
        )

    db.commit()
    db.refresh(mix)

    return mix
