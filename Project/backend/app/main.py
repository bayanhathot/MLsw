"""
File: app/main.py

Purpose:
This is the entry point of the Zonix FastAPI backend.

What this backend does in the MVP:
- Exposes a health endpoint so we can check if the server is alive.
- Accepts a vibe prompt from the frontend.
- Creates a mock AI DJ session.
- Accepts feedback buttons from the frontend.
- Stops an active AI DJ session.

Why this matters:
This turns Zonix from a frontend mockup into a real client/server app.
The frontend becomes the client. This FastAPI app becomes the server.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .schemas import (
    FeedbackRequest,
    SessionResponse,
    StartSessionRequest,
    StopSessionResponse,
)
from .services.session_manager import (
    apply_feedback,
    create_session,
    stop_session,
)


app = FastAPI(
    title="Zonix API",
    description="Backend API for Zonix AI DJ sessions.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# CORS allows the SvelteKit frontend to call this backend.
# During development:
# - frontend dev server runs on localhost:5173
# - frontend Docker/Nginx runs on localhost:8080
# - backend runs on localhost:5000
#
# Without CORS, the browser may block requests between these ports.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict:
    """
    Health endpoint.

    Used to verify that the backend is running.
    """

    return {
        "status": "ok",
        "service": "zonix-backend",
        "version": "0.1.0",
    }


@app.post("/sessions/start", response_model=SessionResponse)
def start_session(request: StartSessionRequest) -> dict:
    """
    Start a new AI DJ session.

    Frontend sends:
    {
        "prompt": "deep work focus with smooth transitions"
    }

    Backend returns:
    - session ID
    - now-playing metadata
    - vibe label
    - simple reasoning text
    """

    prompt = request.prompt.strip()

    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="Prompt cannot be empty.",
        )

    return create_session(prompt)


@app.post("/sessions/{session_id}/feedback", response_model=SessionResponse)
def send_feedback(session_id: str, request: FeedbackRequest) -> dict:
    """
    Apply user feedback to an active AI DJ session.

    Example feedback:
    - Good vibe
    - More energy
    - Less vocals
    - Smoother
    """

    feedback = request.feedback.strip()

    if not feedback:
        raise HTTPException(
            status_code=400,
            detail="Feedback cannot be empty.",
        )

    updated_session = apply_feedback(session_id, feedback)

    if updated_session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found.",
        )

    return updated_session


@app.post("/sessions/{session_id}/stop", response_model=StopSessionResponse)
def stop_ai_dj_session(session_id: str) -> dict:
    """
    Stop an active AI DJ session.
    """

    result = stop_session(session_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found.",
        )

    return result