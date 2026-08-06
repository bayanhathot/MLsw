"""
mixes.py

Pydantic schemas for persisted mixes.

Not to be confused with the ephemeral MixSegment/StartMixRequest/
StartMixResponse schemas defined inside routers/mixes.py, which power
the older, frontend-disconnected MVP demo endpoint (POST /mixes/start).
That endpoint never saves anything; these schemas describe the real,
persisted version created when a post is made.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MixSegmentRead(BaseModel):
    """
    One track in a persisted mix's playback queue.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    title: str
    artist: str
    audio_url: str
    cover_url: str | None = None
    start_second: int
    end_second: int
    transition_to_next: str
    source: str
    source_track_id: str


class MixRead(BaseModel):
    """
    A persisted mix: the prompt that generated it, plus its ordered
    segment queue.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt: str
    created_at: datetime
    segments: list[MixSegmentRead]
