"""
Mixes router for Zonix.

This router exposes API endpoints related to generating AI DJ mixes.

Current endpoint:
POST /mixes/start

Main idea:
The user does not receive one song.
Instead, the backend creates a mix queue made of multiple song segments.

Current MVP flow:
1. Frontend sends a prompt to POST /mixes/start.
2. Backend searches Audius for relevant tracks.
3. Each returned track becomes a simple 45-second segment.
4. Backend returns an ordered segment queue.
5. Frontend will later play the queue and crossfade between segments.

Important:
This router creates a "mix plan", not a real audio file.
Real audio cutting, beat detection, and crossfading are future work.

Future improvements:
- Save mix sessions in PostgreSQL.
- Save tracks and generated segments in PostgreSQL.
- Generate smarter segments instead of always using 0-45 seconds.
- Use feedback buttons to choose the next segment.
- Add real crossfade/playback logic on the frontend.
"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.audius_service import search_tracks


router = APIRouter(prefix="/mixes", tags=["mixes"])


class StartMixRequest(BaseModel):
    """
      Request body for creating a new mix.

      Example:
      {
          "prompt": "chill electronic focus"
      }

      The prompt describes the vibe the user wants.
      """
    prompt: str = Field(..., min_length=1, max_length=300)


class MixSegment(BaseModel):
    """
    Represents one segment in the generated mix queue.

    In the MVP, every segment is created from one Audius track.
    Later, a segment should represent the best part of a song,
    such as the chorus, drop, vocal part, or emotional section.
    """
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


class StartMixResponse(BaseModel):
    """
    Response returned by POST /mixes/start.

    Fields:
        session_id:
            Unique id for this generated mix.

        prompt:
            The original prompt sent by the user.

        segments:
            Ordered list of segments that the frontend should play.
    """
    session_id: str
    prompt: str
    segments: list[MixSegment]


@router.post("/start", response_model=StartMixResponse)
def start_mix(request: StartMixRequest):
    """
       Start a new AI DJ mix.

       Flow:
       1. Receive a prompt from the frontend.
       2. Search Audius for tracks related to the prompt.
       3. Convert each track into a temporary 45-second segment.
       4. Return the ordered segment queue.

       Example:
           Prompt: "chill electronic focus"

           Returned queue:
           - Segment 1: Track A, seconds 0-45
           - Segment 2: Track B, seconds 0-45
           - Segment 3: Track C, seconds 0-45

       The frontend will later play these segments in order and add crossfade.
       """
    tracks = search_tracks(request.prompt, limit=5)

    if not tracks:
        raise HTTPException(
            status_code=404,
            detail="No tracks found for this prompt",
        )

    segments = []

    for index, track in enumerate(tracks):
        duration = track.get("duration") or 60

        # MVP fake segmentation:
        # each track becomes one 45-second segment.
        start_second = 0
        end_second = min(45, duration)

        segments.append(
            {
                "position": index + 1,
                "title": track["title"],
                "artist": track["artist"],
                "audio_url": track["audio_url"],
                "cover_url": track["cover_url"],
                "start_second": start_second,
                "end_second": end_second,
                "transition_to_next": "crossfade",
                "source": track["source"],
                "source_track_id": track["source_track_id"],
            }
        )

    return {
        "session_id": f"mix_{uuid4().hex[:8]}",
        "prompt": request.prompt,
        "segments": segments,
    }