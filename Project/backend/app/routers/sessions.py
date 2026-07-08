"""
sessions.py

Temporary public demo session router.

Current demo behavior:
- Anyone can write a prompt.
- User does NOT need to be logged in.
- Backend receives the prompt.
- Backend ignores real AI mixing for now.
- Backend returns the hardcoded demo.mp3 file.
- Frontend plays the MP3.

Later:
- Public users can still try the demo.
- Logged-in users can save mixes, like segments, view history, etc.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
)


class StartSessionRequest(BaseModel):
    """
    Request body from the frontend.

    The frontend sends:
    {
      "prompt": "some vibe prompt"
    }
    """

    prompt: str = Field(min_length=1, max_length=1000)


def build_demo_session(prompt: str):
    """
    Build a frontend-compatible demo session.

    Important:
    The frontend expects fields like:
    - id
    - prompt
    - vibeLabel
    - nowPlaying
    - audioUrl
    - reasoning

    Because this is public demo mode, there is no user_id.
    """

    return {
        "id": "public-demo-session",
        "prompt": prompt,
        "vibeLabel": "Demo hardcoded MP3",
        "audioUrl": "http://localhost:5000/static/audio/demo.mp3",
        "nowPlaying": {
            "title": "Zonix Demo Track",
            "artist": "Hardcoded Demo Catalog",
            "album": "Zonix MVP Demo",
            "coverUrl": "/brand/zonix-logo.svg",
            "vibeLabel": "Demo hardcoded MP3",
            "role": "Demo playback",
        },
        "reasoning": {
            "selectedMoment": "Demo mode is active, so the backend always selects the same MP3 file.",
            "transitionPlan": "No real transition model is running yet.",
            "nextDirection": "Later this endpoint will return a generated mix instead of the hardcoded file.",
        },
    }


@router.post("/start")
def start_session(request: StartSessionRequest):
    """
    Start a public demo session.

    No login required.

    Anyone can enter a prompt and receive the hardcoded demo MP3.
    """

    return build_demo_session(prompt=request.prompt)


@router.post("/{session_id}/feedback")
def send_feedback(session_id: str):
    """
    Temporary public feedback endpoint.

    For now, this does not store feedback in the database.
    Later, feedback storage should require login.
    """

    return build_demo_session(
        prompt="Feedback received in public demo mode."
    )


@router.post("/{session_id}/stop")
def stop_session(session_id: str):
    """
    Temporary public stop endpoint.

    The frontend can pause/stop the audio locally.
    This endpoint only confirms the stop request.
    """

    return {
        "session_id": session_id,
        "status": "stopped",
        "message": "Demo session stopped.",
    }