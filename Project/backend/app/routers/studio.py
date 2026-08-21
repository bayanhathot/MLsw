"""Signed-in CueMix Studio API; existing DJ and generated-mix routes stay unchanged."""

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import (
    MixRead,
    SavedSegmentCreate,
    SavedSegmentRead,
    SavedSegmentUpdate,
    StudioAssistantRead,
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
    Track,
)
from app.services import audius_service, studio_ai_client, studio_service
from app.services.pipeline import external_track_cache
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


def _catalog_read(row: CatalogTrack) -> StudioTrackRead:
    return StudioTrackRead(
        source_type="catalog",
        source_track_id=str(row.id),
        title=row.title,
        artist=row.artist,
        album=row.album,
        genre=row.genre,
        vibe=row.vibe_label,
        duration_ms=row.duration_seconds * 1000,
        audio_url=public_api_url(f"/catalog/tracks/{row.id}/audio"),
        cover_url=(
            public_api_url(f"/catalog/tracks/{row.id}/cover")
            if row.cover_storage_name
            else None
        ),
        analysis_status=row.analysis_status,
        suggested_start_ms=(row.segment_start_second or 0) * 1000,
        suggested_end_ms=(row.segment_end_second or row.duration_seconds) * 1000,
        bpm=row.bpm,
        musical_key=row.musical_key,
        camelot=row.camelot,
    )


def _external_read(row: ExternalTrack) -> StudioTrackRead:
    metadata = row.provider_metadata_json or {}
    return StudioTrackRead(
        source_type="audius",
        source_track_id=row.external_id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        genre=row.genre,
        vibe=metadata.get("vibe"),
        duration_ms=row.duration_sec * 1000,
        audio_url=public_api_url(f"/studio/tracks/audius/{row.external_id}/audio"),
        cover_url=metadata.get("cover_url"),
        analysis_status=row.analysis_status,
        suggested_start_ms=(row.segment_start_second or 0) * 1000,
        suggested_end_ms=(row.segment_end_second or min(30, row.duration_sec)) * 1000,
        bpm=row.bpm,
        musical_key=row.musical_key,
        camelot=row.camelot,
    )


def _remember_audius_results(db: Session, raw_tracks: list[dict]) -> list[ExternalTrack]:
    tracks = [
        Track(
            source="audius",
            source_track_id=str(item["source_track_id"]),
            title=str(item.get("title") or "Unknown title"),
            artist=str(item.get("artist") or "Unknown artist"),
            audio_url=str(item["audio_url"]),
            cover_url=item.get("cover_url"),
            duration_seconds=max(0, int(item.get("duration") or 0)),
            genre=item.get("genre"),
            vibe=item.get("mood"),
            tags=item.get("tags"),
        )
        for item in raw_tracks
        if item.get("source_track_id") and item.get("audio_url") and int(item.get("duration") or 0) > 0
    ]
    external_track_cache.enrich_and_dispatch(db, tracks)
    ids = [track.source_track_id for track in tracks]
    existing = {
        row.external_id: row
        for row in db.query(ExternalTrack)
        .filter(ExternalTrack.source == "audius", ExternalTrack.external_id.in_(ids))
        .all()
    }
    for track in tracks:
        row = existing.get(track.source_track_id)
        metadata = {"tags": track.tags, "vibe": track.vibe, "cover_url": track.cover_url}
        if row is None:
            row = ExternalTrack(
                source="audius",
                external_id=track.source_track_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                genre=track.genre,
                duration_sec=track.duration_seconds,
                provider_metadata_json=metadata,
                analysis_status="pending",
            )
            db.add(row)
            existing[track.source_track_id] = row
        else:
            row.title = track.title
            row.artist = track.artist
            row.genre = track.genre
            row.duration_sec = track.duration_seconds
            row.provider_metadata_json = metadata
    db.commit()
    return [existing[track.source_track_id] for track in tracks]


@router.get("/tracks/search", response_model=list[StudioTrackRead])
def search_tracks(
    q: str = Query(default="", max_length=120),
    source: str = Query(default="all", pattern="^(all|catalog|audius)$"),
    limit: int = Query(default=20, ge=1, le=50),
    _: None = Depends(_studio_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results: list[StudioTrackRead] = []
    if source in {"all", "catalog"}:
        catalog = db.query(CatalogTrack).filter(
            or_(CatalogTrack.visibility == "public", CatalogTrack.owner_id == current_user.id),
            CatalogTrack.duration_seconds > 0,
            CatalogTrack.analysis_status != "failed",
        )
        if q.strip():
            pattern = f"%{q.strip()}%"
            catalog = catalog.filter(
                or_(CatalogTrack.title.ilike(pattern), CatalogTrack.artist.ilike(pattern))
            )
        results.extend(_catalog_read(row) for row in catalog.order_by(CatalogTrack.id.desc()).limit(limit))
    if source in {"all", "audius"} and q.strip() and len(results) < limit:
        raw = audius_service.search_tracks(q.strip(), limit=limit - len(results))
        results.extend(_external_read(row) for row in _remember_audius_results(db, raw))
    return results[:limit]


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
