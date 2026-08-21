"""Fail-open proxy from the authoritative backend to studio-ai-service."""

import os

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.schemas import (
    StudioAssistantRead,
    StudioAssistantRecommendation,
    StudioAssistantRequest,
)
from app.services import music_identity_service, studio_service


def _unavailable(message: str) -> StudioAssistantRead:
    return StudioAssistantRead(
        available=False,
        recommendation=StudioAssistantRecommendation(
            recommendation_type="unavailable",
            explanation=message,
            reason_tags=["manual-editing-available"],
            confidence=0,
            requires_user_confirmation=True,
        ),
    )


def _context(db: Session, user_id: int, request: StudioAssistantRequest) -> dict:
    active = None
    if request.active_saved_segment_id is not None:
        row = studio_service.owned_segment(db, user_id, request.active_saved_segment_id)
        active = {
            "id": row.id,
            "title": row.title,
            "artist": row.artist,
            "duration_ms": row.track_duration_ms,
            "start_ms": row.start_ms,
            "end_ms": row.end_ms,
            "bpm": row.bpm,
            "key": row.camelot or row.musical_key,
            "genre": row.genre,
            "vibe": row.vibe,
        }
    mix = None
    if request.mix_id is not None:
        row = studio_service.owned_studio_mix(db, user_id, request.mix_id)
        mix = {
            "id": row.id,
            "revision": row.revision,
            "title": row.title,
            "items": [
                {
                    "item_id": item.id,
                    "saved_segment_id": item.saved_segment_id,
                    "title": item.title,
                    "artist": item.artist,
                    "start_ms": item.source_start_ms,
                    "end_ms": item.source_end_ms,
                    "bpm": item.bpm,
                    "key": item.camelot or item.musical_key,
                    "transition_type": item.transition_type,
                    "transition_duration_ms": item.transition_duration_ms,
                    "compatibility_score": item.compatibility_score,
                }
                for item in row.segments
            ],
        }
    identity = music_identity_service.build_music_identity(db, user_id, "30d")
    return {
        "active_segment": active,
        "mix": mix,
        "listener_summary": identity["summary"],
        "top_genres": identity["genres"][:3],
        "top_vibes": identity["vibes"][:3],
    }


def _validate_recommendation(
    db: Session,
    user_id: int,
    request: StudioAssistantRequest,
    recommendation: StudioAssistantRecommendation,
) -> None:
    candidate_id = recommendation.candidate_id or request.active_saved_segment_id
    if recommendation.proposed_start_ms is not None or recommendation.proposed_end_ms is not None:
        if candidate_id is None:
            raise ValueError("Segment-bound suggestions require an owned candidate.")
        saved = studio_service.owned_segment(db, user_id, candidate_id)
        if recommendation.proposed_start_ms is None or recommendation.proposed_end_ms is None:
            raise ValueError("Both proposed bounds are required.")
        studio_service.validate_bounds(
            recommendation.proposed_start_ms,
            recommendation.proposed_end_ms,
            saved.track_duration_ms,
        )
        recommendation.candidate_id = candidate_id
    if recommendation.proposed_order is not None:
        if request.mix_id is None:
            raise ValueError("An order suggestion requires a mix.")
        mix = studio_service.owned_studio_mix(db, user_id, request.mix_id)
        expected = {item.id for item in mix.segments}
        if set(recommendation.proposed_order) != expected or len(
            recommendation.proposed_order
        ) != len(expected):
            raise ValueError("Suggested order does not match the current mix.")
    if recommendation.transition_change is not None:
        if request.mix_id is None:
            raise ValueError("A transition suggestion requires a mix.")
        mix = studio_service.owned_studio_mix(db, user_id, request.mix_id)
        item = next(
            (
                row
                for row in mix.segments
                if row.id == recommendation.transition_change.item_id
            ),
            None,
        )
        if item is None:
            raise ValueError("Suggested transition item is not in the current mix.")
        ordered = sorted(mix.segments, key=lambda row: row.position)
        if ordered[-1].id == item.id:
            raise ValueError("The final mix item has no outgoing transition.")
        if (
            recommendation.transition_change.transition_type == "cut"
            and recommendation.transition_change.duration_ms != 0
        ):
            raise ValueError("A cut transition must have zero duration.")


def chat(
    db: Session, user_id: int, request: StudioAssistantRequest
) -> StudioAssistantRead:
    base_url = os.getenv("STUDIO_AI_URL", "").strip().rstrip("/")
    if not base_url:
        return _unavailable("AI Mix Assistant is not configured; manual Studio remains available.")
    timeout = max(1.0, min(45.0, float(os.getenv("STUDIO_AI_TIMEOUT_SECONDS", "20"))))
    payload = {
        "messages": [message.model_dump() for message in request.messages],
        "context": _context(db, user_id, request),
    }
    headers = {}
    token = os.getenv("STUDIO_AI_INTERNAL_TOKEN", "").strip()
    if token:
        headers["X-Studio-AI-Token"] = token
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            response = client.post(
                f"{base_url}/internal/studio-ai/chat", json=payload, headers=headers
            )
            response.raise_for_status()
        recommendation = StudioAssistantRecommendation.model_validate(response.json())
        _validate_recommendation(db, user_id, request, recommendation)
        return StudioAssistantRead(available=True, recommendation=recommendation)
    except (httpx.HTTPError, HTTPException, ValueError, TypeError, ValidationError):
        return _unavailable(
            "AI Mix Assistant could not produce a grounded recommendation; your draft was not changed."
        )
