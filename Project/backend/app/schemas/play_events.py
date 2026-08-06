"""
play_events.py

Pydantic schemas for reporting real listening time.
"""

from pydantic import BaseModel, Field


class PlayEventCreate(BaseModel):
    """
    Request body for POST /play-events.

    Sent by the frontend player on a ~15s heartbeat and on
    pause/segment-advance/unmount - see PostCard.svelte.
    """

    mix_id: int
    segment_id: int
    seconds_listened: int = Field(gt=0, le=60)
    event_type: str = Field(pattern="^(heartbeat|pause|ended|unmount)$")
    post_id: int | None = None


class PlayEventRead(BaseModel):
    """
    Response shape for POST /play-events.

    seconds_listened echoes back the clamped value actually recorded,
    not necessarily what the client sent.
    """

    id: int
    seconds_listened: int
