"""
File: app/services/session_manager.py

Purpose:
This file contains the temporary backend logic for AI DJ sessions.

Current MVP behavior:
- Create a session from a user prompt.
- Choose a mock song moment based on simple keyword rules.
- Store the session in memory.
- Update the session when the user gives feedback.
- Stop the session when requested.

Important:
This is NOT the final ML model. It is a clean mock backend that lets the
frontend and backend communicate like a real product.

Later, this file can be replaced or expanded with:
- real song catalog retrieval
- segment scoring
- transition planning
- audio rendering
- feedback learning
"""

from uuid import uuid4


# In-memory session storage.
# This resets every time the backend restarts.
# Later, this can become SQLite/PostgreSQL/Redis.
SESSIONS: dict[str, dict] = {}


def choose_demo_track(prompt: str) -> dict:
    """
    Select a demo track/moment based on the prompt.

    For the MVP, we use simple keyword matching.
    Later, this becomes:
    prompt embedding + segment retrieval + transition model.

    Args:
        prompt: User text describing the desired vibe.

    Returns:
        A dictionary with now-playing information and AI reasoning.
    """

    normalized_prompt = prompt.lower()

    if "gym" in normalized_prompt or "energy" in normalized_prompt:
        return {
            "vibeLabel": "Gym energy",
            "nowPlaying": {
                "title": "Momentum Loop",
                "artist": "Zonix AI DJ",
                "album": "Workout Demo Catalog",
                "coverUrl": "/brand/zonix-logo.svg",
                "vibeLabel": "Gym energy",
            },
            "reasoning": {
                "selectedMoment": "Selected a stronger rhythmic moment to match the requested energy.",
                "transitionPlan": "The next transition will keep the beat stable and avoid sudden drops.",
                "nextDirection": "Move toward higher momentum if the user keeps asking for more energy.",
            },
        }

    if "arabic" in normalized_prompt or "vocals" in normalized_prompt:
        return {
            "vibeLabel": "Emotional Arabic vocals",
            "nowPlaying": {
                "title": "Midnight Whispers",
                "artist": "Hassan Al-Shafei",
                "album": "Private Demo Catalog",
                "coverUrl": "/brand/zonix-logo.svg",
                "vibeLabel": "Emotional Arabic vocals",
            },
            "reasoning": {
                "selectedMoment": "Selected a warm vocal moment because the prompt asked for emotional vocals.",
                "transitionPlan": "The next transition will stay smooth and avoid cutting the vocal phrase too early.",
                "nextDirection": "Keep the flow emotional, slow, and vocal-focused.",
            },
        }

    if "coding" in normalized_prompt or "focus" in normalized_prompt or "work" in normalized_prompt:
        return {
            "vibeLabel": "Deep work focus",
            "nowPlaying": {
                "title": "Focus Loop 01",
                "artist": "Zonix Autonomous Brain",
                "album": "Focus Demo Catalog",
                "coverUrl": "/brand/zonix-logo.svg",
                "vibeLabel": "Deep work focus",
            },
            "reasoning": {
                "selectedMoment": "Selected a low-distraction section that supports concentration.",
                "transitionPlan": "The next transition will keep the same calm energy without sudden changes.",
                "nextDirection": "Continue with steady, minimal, focus-friendly moments.",
            },
        }

    return {
        "vibeLabel": "Smooth flow",
        "nowPlaying": {
            "title": "Smooth Flow Demo",
            "artist": "Zonix AI DJ",
            "album": "General Demo Catalog",
            "coverUrl": "/brand/zonix-logo.svg",
            "vibeLabel": "Smooth flow",
        },
        "reasoning": {
            "selectedMoment": "Selected a balanced moment because the prompt was general.",
            "transitionPlan": "The next transition will keep the session smooth and adaptable.",
            "nextDirection": "Wait for feedback to decide whether to increase energy or calm it down.",
        },
    }


def create_session(prompt: str) -> dict:
    """
    Create a new AI DJ session.

    Args:
        prompt: User vibe prompt from the frontend.

    Returns:
        A complete session dictionary.
    """

    track_data = choose_demo_track(prompt)
    session_id = f"session_{uuid4().hex[:8]}"

    session = {
        "id": session_id,
        "prompt": prompt,
        "status": "playing",
        "vibeLabel": track_data["vibeLabel"],
        "nowPlaying": track_data["nowPlaying"],
        "audioUrl": "",
        "reasoning": track_data["reasoning"],
        "selectedFeedback": None,
    }

    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> dict | None:
    """
    Get an existing session by ID.

    Returns None if the session does not exist.
    """

    return SESSIONS.get(session_id)


def apply_feedback(session_id: str, feedback: str) -> dict | None:
    """
    Store user feedback on the session.

    Current MVP:
    We only save the selected feedback.

    Later:
    This feedback should affect the next selected segment.
    """

    session = SESSIONS.get(session_id)

    if session is None:
        return None

    session["selectedFeedback"] = feedback
    session["reasoning"]["nextDirection"] = f"User asked for: {feedback}. The next moment should adapt to that."

    return session


def stop_session(session_id: str) -> dict | None:
    """
    Stop an existing session.

    Current MVP:
    We mark the session as stopped.

    Later:
    This could also cancel a rendering job or close an audio stream.
    """

    session = SESSIONS.get(session_id)

    if session is None:
        return None

    session["status"] = "stopped"

    return {
        "session_id": session_id,
        "status": "stopped",
        "message": "AI DJ session stopped.",
    }