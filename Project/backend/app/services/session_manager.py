"""Persistent, deterministic AI-DJ session behavior."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.database.models.session import DJSession, SessionFeedback, UserPreference
from app.schemas import SessionRead
from app.services.prompt_parser import parse_prompt

AUDIO_URL = public_api_url("/static/audio/zonix-demo.wav")
COVER_URL = "/brand/zonix-logo.svg"

TRACKS = {
    "energy": {
        "vibe": "Gym energy",
        "title": "Momentum Loop",
        "artist": "Zonix AI DJ",
        "album": "Workout Demo Catalog",
        "role": "Energy lift",
        "selected": "Selected a stronger rhythmic moment to match the requested energy.",
        "transition": "The next transition will keep a stable beat and avoid sudden drops.",
    },
    "vocals": {
        "vibe": "Emotional vocals",
        "title": "Midnight Whispers",
        "artist": "Zonix AI DJ",
        "album": "Vocal Demo Catalog",
        "role": "Vocal center",
        "selected": "Selected a warm vocal moment because the prompt asked for expressive vocals.",
        "transition": "The next transition will not cut the vocal phrase early.",
    },
    "focus": {
        "vibe": "Deep work focus",
        "title": "Focus Loop 01",
        "artist": "Zonix AI DJ",
        "album": "Focus Demo Catalog",
        "role": "Low-distraction flow",
        "selected": "Selected a low-distraction section that supports concentration.",
        "transition": "The next transition will keep calm energy without sudden changes.",
    },
    "smooth": {
        "vibe": "Smooth flow",
        "title": "Smooth Flow Demo",
        "artist": "Zonix AI DJ",
        "album": "General Demo Catalog",
        "role": "Balanced opener",
        "selected": "Selected a balanced moment that leaves room for feedback.",
        "transition": "The next transition will remain smooth and adaptable.",
    },
}

PREFERENCE_TRACKS = {
    "more_energy": "energy",
    "less_vocals": "focus",
    "smoother": "smooth",
    "energy": "energy",
    "vocals": "vocals",
    "focus": "focus",
    "smooth": "smooth",
}


def _normalize_feedback(feedback: str, current_track_key: str) -> str:
    value = feedback.strip().lower().replace(" ", "_")
    if "energy" in value:
        return "more_energy"
    if "vocal" in value:
        return "less_vocals"
    if "smooth" in value:
        return "smoother"
    if "good" in value or "like" in value:
        # Praise reinforces what is actually playing, rather than teaching a
        # generic preference that may contradict the session context.
        return current_track_key
    return "custom"


def _initial_track(prompt: str, db: Session, user_id: int | None) -> str:
    intent = parse_prompt(prompt)
    text = prompt.lower()
    if intent.energy == "high" or any(word in text for word in ("gym", "energy", "workout")):
        return "energy"
    if intent.vocals == "more" or any(word in text for word in ("arabic", "vocal")):
        return "vocals"
    if intent.energy == "low" or any(word in text for word in ("coding", "focus", "work")):
        return "focus"

    if user_id is not None:
        preferences = (
            db.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.score > 0)
            .order_by(UserPreference.score.desc(), UserPreference.count.desc())
            .all()
        )
        for preference in preferences:
            mapped = PREFERENCE_TRACKS.get(preference.feedback)
            if mapped:
                return mapped
            if preference.feedback == "good_vibe":
                # Compatibility for rows created before contextual praise was
                # introduced. Recover the most recent praised session instead
                # of silently treating all praise as "smooth".
                praised = (
                    db.query(DJSession)
                    .join(SessionFeedback, SessionFeedback.session_id == DJSession.id)
                    .filter(
                        DJSession.user_id == user_id,
                        SessionFeedback.normalized_feedback == "good_vibe",
                    )
                    .order_by(SessionFeedback.id.desc())
                    .first()
                )
                if praised and praised.track_key in TRACKS:
                    return praised.track_key
    return "smooth"


def _next_direction(session: DJSession) -> str:
    if session.selected_feedback:
        return f"Applied {session.selected_feedback}; the selected moment and next transition now reflect it."
    return "Give feedback to steer energy, vocals, or transition smoothness."


def serialize_session(session: DJSession) -> SessionRead:
    track = TRACKS[session.track_key]
    return SessionRead(
        id=session.id,
        prompt=session.prompt,
        status=session.status,
        vibeLabel=track["vibe"],
        audioUrl=AUDIO_URL,
        nowPlaying={
            "title": track["title"],
            "artist": track["artist"],
            "album": track["album"],
            "coverUrl": COVER_URL,
            "vibeLabel": track["vibe"],
            "role": track["role"],
        },
        reasoning={
            "selectedMoment": track["selected"],
            "transitionPlan": track["transition"],
            "nextDirection": _next_direction(session),
        },
        selectedFeedback=session.selected_feedback,
    )


def create_session(db: Session, prompt: str, user_id: int | None = None) -> SessionRead:
    session = DJSession(
        id=f"session_{uuid4().hex}",
        user_id=user_id,
        prompt=prompt,
        status="playing",
        track_key=_initial_track(prompt, db, user_id),
        vibe_label="pending",
    )
    session.vibe_label = TRACKS[session.track_key]["vibe"]
    db.add(session)
    db.commit()
    db.refresh(session)
    return serialize_session(session)


def get_session(db: Session, session_id: str) -> DJSession | None:
    return db.query(DJSession).filter(DJSession.id == session_id).first()


def apply_feedback(db: Session, session: DJSession, feedback: str) -> SessionRead:
    normalized = _normalize_feedback(feedback, session.track_key)
    session.selected_feedback = feedback
    session.track_key = {
        "more_energy": "energy",
        "less_vocals": "focus",
        "smoother": "smooth",
    }.get(normalized, session.track_key)
    session.vibe_label = TRACKS[session.track_key]["vibe"]
    db.add(
        SessionFeedback(
            session_id=session.id,
            user_id=session.user_id,
            feedback=feedback,
            normalized_feedback=normalized,
        )
    )

    if session.user_id is not None and normalized in PREFERENCE_TRACKS:
        preference = (
            db.query(UserPreference)
            .filter_by(user_id=session.user_id, feedback=normalized)
            .first()
        )
        if preference is None:
            preference = UserPreference(
                user_id=session.user_id, feedback=normalized, count=0, score=0
            )
            db.add(preference)
        preference.count += 1
        # Score is preference strength, not sentiment.  "Less vocals" is a
        # positive direction the user wants remembered.
        preference.score += 1

    db.commit()
    db.refresh(session)
    return serialize_session(session)


def stop_session(db: Session, session: DJSession) -> dict:
    session.status = "stopped"
    db.commit()
    return {"session_id": session.id, "status": "stopped", "message": "AI DJ session stopped."}
