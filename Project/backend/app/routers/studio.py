"""Signed-in CueMix Studio API; existing DJ and generated-mix routes stay unchanged."""

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.external_track import ExternalTrack
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import (
    MixRead,
    SavedSegmentCreate,
    SavedSegmentRead,
    SavedSegmentUpdate,
    StudioAssistantRead,
    StudioAssistantPlanApplyRead,
    StudioAssistantPlanApplyRequest,
    StudioAssistantRequest,
    StudioAutoMixRequest,
    StudioBehaviorEventCreate,
    StudioBehaviorSignalRead,
    StudioMixCreate,
    StudioMixItemAdd,
    StudioMixReorder,
    StudioMixUpdate,
    StudioTrackRead,
    StudioTransitionUpdate,
)
from app.services import audius_service, studio_ai_client, studio_service
from app.services.pipeline.dependencies import (
    get_audio_renderer,
    get_transition_planner,
    get_vibe_understander,
)
from app.services.pipeline.interfaces import (
    AudioRenderer,
    TransitionPlanner,
    VibeUnderstander,
)

router = APIRouter(prefix="/studio", tags=["studio"])


def _studio_enabled() -> None:
    if os.getenv("STUDIO_ENABLED", "true").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="Studio not found.")


@router.get("/tracks/search", response_model=list[StudioTrackRead])
def search_tracks(
    q: str = Query(default="", max_length=120),
    source: str = Query(default="all", pattern="^(all|catalog|audius)$"),
    limit: int = Query(default=20, ge=1, le=50),
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.search_tracks(db, current_user.id, q, source, limit)


@router.get("/tracks/audius/{track_id}/audio")
def audius_audio(
    track_id: str,
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del current_user
    row = (
        db.query(ExternalTrack)
        .filter(ExternalTrack.source == "audius", ExternalTrack.external_id == track_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    return RedirectResponse(audius_service.audius_stream_url(track_id), status_code=307)


@router.post("/segments", response_model=SavedSegmentRead, status_code=status.HTTP_201_CREATED)
def create_segment(
    request: SavedSegmentCreate,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.create_saved_segment(db, current_user.id, request)


@router.get("/segments", response_model=list[SavedSegmentRead])
def list_segments(
    q: str = Query(default="", max_length=120),
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.list_saved_segments(db, current_user.id, q)


@router.get("/segments/{segment_id}", response_model=SavedSegmentRead)
def get_segment(
    segment_id: int,
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.owned_segment(db, current_user.id, segment_id)


@router.patch("/segments/{segment_id}", response_model=SavedSegmentRead)
def update_segment(
    segment_id: int,
    request: SavedSegmentUpdate,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = studio_service.owned_segment(db, current_user.id, segment_id)
    return studio_service.update_saved_segment(db, row, request)


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(
    segment_id: int,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = studio_service.owned_segment(db, current_user.id, segment_id)
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/segments/{segment_id}/preview")
def preview_segment(
    segment_id: int,
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = studio_service.owned_segment(db, current_user.id, segment_id)
    return RedirectResponse(row.source_audio_url, status_code=307)


@router.post("/mixes", response_model=MixRead, status_code=status.HTTP_201_CREATED)
def create_mix(
    request: StudioMixCreate,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.create_studio_mix(
        db, current_user.id, request.title, request.description
    )


@router.get("/mixes", response_model=list[MixRead])
def list_mixes(
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.list_studio_mixes(db, current_user.id)


@router.get("/mixes/{mix_id}", response_model=MixRead)
def get_mix(
    mix_id: int,
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_service.owned_studio_mix(db, current_user.id, mix_id)


@router.patch("/mixes/{mix_id}", response_model=MixRead)
def update_mix(
    mix_id: int,
    request: StudioMixUpdate,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.update_studio_mix(db, mix, request)


@router.post("/mixes/{mix_id}/items", response_model=MixRead)
def add_mix_item(
    mix_id: int,
    request: StudioMixItemAdd,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    planner: TransitionPlanner = Depends(get_transition_planner),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    saved = studio_service.owned_segment(db, current_user.id, request.saved_segment_id)
    return studio_service.add_saved_segment(
        db, mix, saved, request.expected_revision, planner
    )


@router.put("/mixes/{mix_id}/items/reorder", response_model=MixRead)
def reorder_mix(
    mix_id: int,
    request: StudioMixReorder,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    planner: TransitionPlanner = Depends(get_transition_planner),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.reorder_mix(
        db, mix, request.segment_ids, request.expected_revision, planner
    )


@router.delete("/mixes/{mix_id}/items/{item_id}", response_model=MixRead)
def remove_mix_item(
    mix_id: int,
    item_id: int,
    expected_revision: int = Query(ge=1),
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    planner: TransitionPlanner = Depends(get_transition_planner),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.remove_mix_item(
        db, mix, item_id, expected_revision, planner
    )


@router.patch("/mixes/{mix_id}/items/{item_id}/transition", response_model=MixRead)
def change_transition(
    mix_id: int,
    item_id: int,
    request: StudioTransitionUpdate,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    planner: TransitionPlanner = Depends(get_transition_planner),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.update_transition(db, mix, item_id, request, planner)


@router.post("/mixes/{mix_id}/items/{item_id}/transition-preview")
def transition_preview(
    mix_id: int,
    item_id: int,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return {"audio_url": studio_service.preview_transition(db, mix, item_id, renderer)}


@router.post("/mixes/{mix_id}/render", response_model=MixRead)
def render_mix(
    mix_id: int,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.enqueue_render_mix(db, mix)


@router.post("/mixes/{mix_id}/publish", response_model=MixRead)
def publish_mix(
    mix_id: int,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.publish_mix(db, mix)


@router.post("/mixes/{mix_id}/duplicate", response_model=MixRead)
def duplicate_mix(
    mix_id: int,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mix = studio_service.owned_studio_mix(db, current_user.id, mix_id)
    return studio_service.duplicate_mix(db, mix, current_user.id)


@router.post("/auto-mix", response_model=MixRead)
def auto_mix(
    request: StudioAutoMixRequest,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    vibe: VibeUnderstander = Depends(get_vibe_understander),
    planner: TransitionPlanner = Depends(get_transition_planner),
):
    return studio_service.auto_mix_from_saved(
        db, current_user.id, request, vibe, planner
    )


@router.post("/behavior", status_code=status.HTTP_201_CREATED)
def add_behavior(
    request: StudioBehaviorEventCreate,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = studio_service.record_behavior(db, current_user.id, request)
    return {"id": event.id, "event_type": event.event_type}


@router.get("/behavior/signals", response_model=list[StudioBehaviorSignalRead])
def get_behavior_signals(
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(studio_service.behavior_signals(db, current_user.id).values())


@router.post("/assistant/chat", response_model=StudioAssistantRead)
def assistant_chat(
    request: StudioAssistantRequest,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return studio_ai_client.chat(db, current_user.id, request)


@router.post("/assistant/apply", response_model=StudioAssistantPlanApplyRead)
def assistant_apply(
    request: StudioAssistantPlanApplyRequest,
    _: None = Depends(_studio_enabled),
    __: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    planner: TransitionPlanner = Depends(get_transition_planner),
):
    mix, saved = studio_service.apply_assistant_plan(
        db, current_user.id, request, planner
    )
    return StudioAssistantPlanApplyRead(mix=mix, saved_segment=saved)
