"""
sessions.py

Temporary demo session router.

For now:
- User writes any prompt.
- Backend receives the prompt.
- Backend ignores real AI mixing.
- Backend returns the hardcoded demo.mp3 URL.
- Frontend plays that MP3.

Later this file will call the real:
- segment selection model
- transition model
- audio renderer
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.database.models.user import User
from app.routers.auth import get_current_user


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


def build_demo_session(prompt: str, user_id: int):
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

    So we return exactly that shape.
    """

    return {
        "id": f"demo-session-user-{user_id}",
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
def start_session(
    request: StartSessionRequest,
    #current_user: User = Depends(get_current_user),  #KEEP only if you want to require authentication for stopping a session
):
    """
    Start a demo session.

    The user must be logged in because get_current_user reads
    the HTTP-only cookie.

    For now, every prompt returns the same demo MP3.
    """

    return build_demo_session(
        prompt=request.prompt,
        user_id=current_user.id,
    )


@router.post("/{session_id}/feedback")
def send_feedback(
    session_id: str,
    # current_user: User = Depends(get_current_user), #KEEP only if you want to require authentication for stopping a session
):
    """
    Temporary feedback endpoint.

    The current frontend expects feedback to return a session object.
    So for demo mode, we return a simple demo session again.
    """

    return build_demo_session(
        prompt="Feedback received in demo mode.",
        user_id=current_user.id,
    )


@router.post("/{session_id}/stop")
def stop_session(
    session_id: str,
    # current_user: User = Depends(get_current_user), #KEEP only if you want to require authentication for stopping a session
):
    """
    Temporary stop endpoint.

    The frontend can pause/stop locally.
    This endpoint only confirms the stop request.
    """

    return {
        "session_id": session_id,
        "user_id": current_user.id,
        "status": "stopped",
        "message": "Demo session stopped.",
    }