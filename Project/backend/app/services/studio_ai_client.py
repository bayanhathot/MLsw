"""Fail-open proxy from the authoritative backend to studio-ai-service."""

import os

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.schemas import (
    StudioAssistantCalculations,
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


def _discovery_results(db: Session, user_id: int, query: str) -> list[dict]:
    """Real search results the model may echo back (never free-associate) --
    the same studio_service.search_tracks core GET /studio/tracks/search
    uses, so a discovery result and a manually searched-for track are always
    the exact same resolvable, addable candidate. See spec §3."""

    tracks = studio_service.search_tracks(db, user_id, query, source="all", limit=10)
    return [
        {
            "source_type": track.source_type,
            "source_track_id": track.source_track_id,
            "title": track.title,
            "artist": track.artist,
            "duration_ms": track.duration_ms,
            "bpm": track.bpm,
            "musical_key": track.musical_key,
            "camelot": track.camelot,
            "vibe": track.vibe,
            "genre": track.genre,
        }
        for track in tracks
    ]


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
                    "position": item.position,
                    "saved_segment_id": item.saved_segment_id,
                    "title": item.title,
                    "artist": item.artist,
                    "start_ms": item.source_start_ms,
                    "end_ms": item.source_end_ms,
                    "duration_ms": max(
                        0, (item.source_end_ms or 0) - (item.source_start_ms or 0)
                    ),
                    "bpm": item.bpm,
                    "key": item.camelot or item.musical_key,
                    "transition_type": item.transition_type,
                    "transition_duration_ms": item.transition_duration_ms,
                    "compatibility_score": item.compatibility_score,
                }
                for item in row.segments
            ],
        }
        current = _plan_calculations(row, None, [])
        mix["current_duration_ms"] = current.current_duration_ms
        mix["current_transition_overlap_ms"] = current.transition_overlap_ms
        mix["current_average_bpm_jump"] = current.average_bpm_jump
    identity = music_identity_service.build_music_identity(db, user_id, "30d")
    discovery_results = (
        _discovery_results(db, user_id, request.discovery_query)
        if request.discovery_query
        else []
    )
    return {
        "active_segment": active,
        "mix": mix,
        "discovery_results": discovery_results,
        "listener_summary": identity["summary"],
        "top_genres": identity["genres"][:3],
        "top_vibes": identity["vibes"][:3],
        "planning_limits": {
            "max_transition_changes": 5,
            "max_removed_item_ids": 5,
            "duration_formula": "sum(item duration) - effective outgoing non-cut overlap",
        },
    }


def _ordered_items(mix, proposed_order: list[int] | None):
    by_id = {item.id: item for item in mix.segments}
    ids = proposed_order or [
        item.id for item in sorted(mix.segments, key=lambda row: row.position)
    ]
    return [by_id[item_id] for item_id in ids]


def _item_duration_ms(item) -> int:
    return max(0, (item.source_end_ms or 0) - (item.source_start_ms or 0))


def _plan_calculations(
    mix, proposed_order: list[int] | None, transition_changes: list
) -> StudioAssistantCalculations:
    items = _ordered_items(mix, proposed_order)
    changes = {change.item_id: change for change in transition_changes}
    overlap_ms = 0
    bpm_jumps: list[float] = []
    for index, item in enumerate(items[:-1]):
        following = items[index + 1]
        change = changes.get(item.id)
        transition_type = change.transition_type if change else item.transition_type
        duration_ms = change.duration_ms if change else item.transition_duration_ms
        if transition_type != "cut":
            overlap_ms += max(
                0,
                min(
                    duration_ms,
                    max(0, _item_duration_ms(item) - 1),
                    max(0, _item_duration_ms(following) - 1),
                ),
            )
        if item.bpm is not None and following.bpm is not None:
            bpm_jumps.append(abs(float(item.bpm) - float(following.bpm)))
    selected_ms = sum(_item_duration_ms(item) for item in items)
    proposed_ms = max(0, selected_ms - overlap_ms)
    current_items = _ordered_items(mix, None)
    current_overlap_ms = 0
    for index, item in enumerate(current_items[:-1]):
        following = current_items[index + 1]
        if item.transition_type != "cut":
            current_overlap_ms += max(
                0,
                min(
                    item.transition_duration_ms,
                    max(0, _item_duration_ms(item) - 1),
                    max(0, _item_duration_ms(following) - 1),
                ),
            )
    current_selected_ms = sum(_item_duration_ms(item) for item in current_items)
    return StudioAssistantCalculations(
        current_duration_ms=max(0, current_selected_ms - current_overlap_ms),
        proposed_duration_ms=proposed_ms,
        transition_overlap_ms=overlap_ms,
        average_bpm_jump=(round(sum(bpm_jumps) / len(bpm_jumps), 2) if bpm_jumps else None),
        known_bpm_pairs=len(bpm_jumps),
    )


def _validate_discovery_and_action(
    recommendation: StudioAssistantRecommendation, discovery_context: list[dict]
) -> None:
    """Shared by both the plan and non-plan branches below: discovery_results
    and suggested_action are advisory, not mix-mutating, so they are valid on
    an 'explanation' turn too (a discovery reply, or "you could preview
    this"), not only on a 'plan'. Never trust an echoed track: it must be
    byte-identical (source_type, source_track_id) to something this turn's
    own context["discovery_results"] actually contained -- the model has no
    other legitimate source of a real track id. See spec §3.3, §6."""

    if recommendation.discovery_results:
        available = {
            (item["source_type"], item["source_track_id"]) for item in discovery_context
        }
        for candidate in recommendation.discovery_results:
            if (candidate.source_type, candidate.source_track_id) not in available:
                raise ValueError(
                    "Discovery results must echo only tracks actually returned by search."
                )
    if (
        recommendation.suggested_action in {"preview_transition", "preview_segment"}
        and recommendation.action_target_item_id is None
    ):
        raise ValueError("A preview action requires action_target_item_id.")


def _validate_recommendation(
    db: Session,
    user_id: int,
    request: StudioAssistantRequest,
    recommendation: StudioAssistantRecommendation,
    discovery_context: list[dict],
) -> None:
    _validate_discovery_and_action(recommendation, discovery_context)

    if recommendation.recommendation_type != "plan":
        if (
            recommendation.proposed_order is not None
            or recommendation.transition_changes
            or recommendation.segment_bound_change is not None
            or recommendation.removed_item_ids
            or recommendation.add_item is not None
        ):
            raise ValueError("Only a plan may contain proposed changes.")
        recommendation.base_revision = None
        recommendation.calculations = None
        recommendation.requires_user_confirmation = True
        return

    if (
        recommendation.proposed_order is None
        and not recommendation.transition_changes
        and recommendation.segment_bound_change is None
        and not recommendation.removed_item_ids
        and recommendation.add_item is None
    ):
        raise ValueError("An assistant plan must contain at least one change.")

    has_actual_bound_change = False
    if recommendation.segment_bound_change is not None:
        bound = recommendation.segment_bound_change
        if (
            request.active_saved_segment_id is None
            or bound.candidate_id != request.active_saved_segment_id
        ):
            raise ValueError("Segment-bound plans may only target the active segment.")
        saved = studio_service.owned_segment(db, user_id, bound.candidate_id)
        studio_service.validate_bounds(
            bound.proposed_start_ms,
            bound.proposed_end_ms,
            saved.track_duration_ms,
        )
        has_actual_bound_change = (
            bound.proposed_start_ms != saved.start_ms
            or bound.proposed_end_ms != saved.end_ms
        )

    has_mix_changes = (
        recommendation.proposed_order is not None
        or recommendation.transition_changes
        or recommendation.removed_item_ids
        or recommendation.add_item is not None
    )
    if has_mix_changes:
        if request.mix_id is None:
            raise ValueError("Mix changes require an active mix.")
        mix = studio_service.owned_studio_mix(db, user_id, request.mix_id)
        expected = {item.id for item in mix.segments}

        if recommendation.add_item is not None:
            add = recommendation.add_item
            if add.source_type == "saved_segment":
                studio_service.owned_segment(db, user_id, add.saved_segment_id)
            else:
                available = {
                    (item["source_type"], item["source_track_id"])
                    for item in discovery_context
                }
                if (add.source_type, add.source_track_id) not in available:
                    raise ValueError(
                        "add_item must reference a track from this turn's discovery_results."
                    )
            if (
                add.insert_after_item_id is not None
                and add.insert_after_item_id not in expected
            ):
                raise ValueError("insert_after_item_id is not in the current mix.")

        removed = set(recommendation.removed_item_ids)
        if removed - expected:
            raise ValueError("Removed items must be in the current mix.")
        expected_after_removal = expected - removed

        proposed_order = recommendation.proposed_order
        if proposed_order is not None and (
            set(proposed_order) != expected_after_removal
            or len(proposed_order) != len(expected_after_removal)
        ):
            raise ValueError("Suggested order must contain every remaining item exactly once.")
        effective_order = proposed_order or [
            item.id
            for item in sorted(mix.segments, key=lambda row: row.position)
            if item.id in expected_after_removal
        ]
        current_order = [
            item.id for item in sorted(mix.segments, key=lambda row: row.position)
        ]
        change_ids = [change.item_id for change in recommendation.transition_changes]
        if len(change_ids) != len(set(change_ids)):
            raise ValueError("A plan may change each transition only once.")
        for change in recommendation.transition_changes:
            if change.item_id not in expected_after_removal:
                raise ValueError("Suggested transition item is not in the current mix.")
            if effective_order and effective_order[-1] == change.item_id:
                raise ValueError("The final mix item has no outgoing transition.")
            if change.transition_type == "cut" and change.duration_ms != 0:
                raise ValueError("A cut transition must have zero duration.")
        by_id = {item.id: item for item in mix.segments}
        has_actual_mix_change = (
            bool(removed)
            or recommendation.add_item is not None
            or effective_order != [item_id for item_id in current_order if item_id in expected_after_removal]
            or any(
                change.transition_type != by_id[change.item_id].transition_type
                or change.duration_ms != by_id[change.item_id].transition_duration_ms
                for change in recommendation.transition_changes
            )
        )
        if not has_actual_mix_change and not has_actual_bound_change:
            raise ValueError("Assistant plan does not change the current draft.")
        recommendation.base_revision = mix.revision
        # Post-removal/add calculations aren't derivable from the existing
        # mix's own persisted rows (a removed item is gone; an added one has
        # no MixSegment row yet, only the recommendation's own add_item
        # fields) -- left None rather than approximated here; the backend
        # recomputes the true figure once the plan is actually applied
        # (studio_service.apply_assistant_plan), same as it always has for
        # every other field this endpoint only estimates in advance.
        recommendation.calculations = (
            _plan_calculations(mix, proposed_order, recommendation.transition_changes)
            if not removed and recommendation.add_item is None
            else None
        )
    else:
        if not has_actual_bound_change:
            raise ValueError("Assistant plan does not change the active segment.")
        recommendation.base_revision = None
        recommendation.calculations = None
    recommendation.requires_user_confirmation = True


def chat(
    db: Session, user_id: int, request: StudioAssistantRequest
) -> StudioAssistantRead:
    base_url = os.getenv("STUDIO_AI_URL", "").strip().rstrip("/")
    if not base_url:
        return _unavailable("AI Mix Assistant is not configured; manual Studio remains available.")
    timeout = max(1.0, min(255.0, float(os.getenv("STUDIO_AI_TIMEOUT_SECONDS", "250"))))
    context = _context(db, user_id, request)
    payload = {
        "messages": [message.model_dump() for message in request.messages],
        "context": context,
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
        _validate_recommendation(
            db, user_id, request, recommendation, context["discovery_results"]
        )
        return StudioAssistantRead(available=True, recommendation=recommendation)
    except (httpx.HTTPError, HTTPException, ValueError, TypeError, ValidationError):
        return _unavailable(
            "AI Mix Assistant could not produce a grounded recommendation; your draft was not changed."
        )
