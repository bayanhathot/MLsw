"""
File: app/schemas.py

Purpose:
This file defines the data shapes used by the Zonix backend API.

Why this file exists:
FastAPI uses Pydantic models to validate incoming JSON requests and to document
the API response structure. Instead of passing random dictionaries everywhere,
we define clear request and response models here.

Main models:
- StartSessionRequest: what the frontend sends when the user starts the AI DJ.
- FeedbackRequest: what the frontend sends when the user coaches the DJ.
- SessionResponse: what the backend returns to describe the active AI DJ session.
"""

from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    """
    Request body for POST /sessions/start.

    Example JSON from frontend:
    {
        "prompt": "emotional Arabic vocals with smooth transitions"
    }
    """

    prompt: str


class FeedbackRequest(BaseModel):
    """
    Request body for POST /sessions/{session_id}/feedback.

    Example JSON from frontend:
    {
        "feedback": "More energy"
    }
    """

    feedback: str


class NowPlaying(BaseModel):
    """
    User-facing information about the current song moment.

    Important:
    This is not only a full song. In the real system, this will represent
    the currently selected segment/moment from a song.
    """

    title: str
    artist: str
    album: str
    coverUrl: str
    vibeLabel: str


class AIReasoning(BaseModel):
    """
    Human-readable explanation of the AI DJ decision.

    This should stay simple and user-friendly.
    Do not expose raw model scores in the normal UI.
    """

    selectedMoment: str
    transitionPlan: str
    nextDirection: str


class SessionResponse(BaseModel):
    """
    Response body returned when an AI DJ session is created or updated.

    This is the main contract between frontend and backend for the MVP.
    """

    id: str
    prompt: str
    status: str
    vibeLabel: str
    nowPlaying: NowPlaying
    audioUrl: str
    reasoning: AIReasoning
    selectedFeedback: str | None = None


class StopSessionResponse(BaseModel):
    """
    Response body returned when the user stops the AI DJ session.
    """

    session_id: str
    status: str
    message: str