"""CueMix Studio adapters over canonical tracks, mixes, transitions and DSP."""

import math
import os
from datetime import timedelta
from queue import Full
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.config import public_api_url
from app.core.time import utc_now
from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.database.models.mix import Mix, MixSegment
from app.database.models.mix_social import MixLike
from app.database.models.studio import SavedSegment, StudioBehaviorEvent
from app.schemas import (
    AutoMixMode,
    PromptIntent,
    SavedSegmentCreate,
    SelectedSegment,
    StudioTrackRead,
    Track,
    TransitionPlan,
)
from app.services import audius_service, publish_service, upload_queue
from app.services.pipeline import audio_renderer, external_track_cache
from app.services.pipeline.catalog_retriever import CATALOG_AUDIO_SUBDIR
from app.services.pipeline.interfaces import (
    AudioRenderer,
    TransitionPlanner,
    VibeUnderstander,
)
from app.services.prompt_parser import apply_auto_mix_mode

MIN_SEGMENT_MS = max(500, int(os.getenv("STUDIO_MIN_SEGMENT_MS", "1000")))
MAX_SEGMENT_MS = min(600_000, int(os.getenv("STUDIO_MAX_SEGMENT_MS", "300000")))
MAX_STUDIO_MIX_SEGMENTS = 50


def _catalog_accessible(row: CatalogTrack, user_id: int) -> bool:
    return row.visibility == "public" or row.owner_id == user_id


def _catalog_audio_url(track_id: int) -> str:
    return public_api_url(f"/catalog/tracks/{track_id}/audio")


def _audius_audio_url(track_id: str) -> str:
    return public_api_url(f"/studio/tracks/audius/{track_id}/audio")


def _catalog_track(row: CatalogTrack) -> Track:
    return Track(
        source="catalog",
        source_track_id=str(row.id),
        title=row.title,
        artist=row.artist,
        album=row.album,
        audio_url=_catalog_audio_url(row.id),
        cover_url=(
            public_api_url(f"/catalog/tracks/{row.id}/cover")
            if row.cover_storage_name
            else None
        ),
        duration_seconds=row.duration_seconds,
        genre=row.genre,
        vibe=row.vibe_label,
        vibe_label=row.vibe_label,
        catalog_track_id=row.id,
        local_path=str(upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / row.storage_name),
    )


def _external_track(row: ExternalTrack) -> Track:
    metadata = row.provider_metadata_json or {}
    return Track(
        source="audius",
        source_track_id=row.external_id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        audio_url=audius_service.audius_stream_url(row.external_id),
        cover_url=metadata.get("cover_url"),
        duration_seconds=row.duration_sec,
        genre=row.genre,
        vibe=metadata.get("vibe"),
        tags=metadata.get("tags"),
        external_track_id=row.id,
    )


def _analysis_values(row) -> dict:
    return {
        "analysis_version": row.analysis_version,
        "bpm": row.bpm,
        "bpm_confidence": row.bpm_confidence,
        "musical_key": row.musical_key,
        "key_mode": row.key_mode,
        "camelot": row.camelot,
        "key_confidence": row.key_confidence,
        "integrated_loudness_lufs": row.integrated_loudness_lufs,
        "phrase_boundaries_json": row.phrase_boundaries_json,
    }


def _phrase_boundaries_ms(values: list | None, duration_ms: int) -> list[int]:
    """Expose persisted analysis markers in Studio's canonical millisecond unit."""
    return sorted(
        {
            max(0, min(duration_ms, round(float(value) * 1000)))
            for value in (values or [])
            if isinstance(value, (int, float))
        }
    )


def _catalog_track_read(row: CatalogTrack) -> StudioTrackRead:
    duration_ms = row.duration_seconds * 1000
    return StudioTrackRead(
        source_type="catalog",
        source_track_id=str(row.id),
        title=row.title,
        artist=row.artist,
        album=row.album,
        genre=row.genre,
        vibe=row.vibe_label,
        duration_ms=duration_ms,
        audio_url=_catalog_audio_url(row.id),
        cover_url=(
            public_api_url(f"/catalog/tracks/{row.id}/cover")
            if row.cover_storage_name
            else None
        ),
        analysis_status=row.analysis_status,
        suggested_start_ms=(row.segment_start_second or 0) * 1000,
        suggested_end_ms=(row.segment_end_second or row.duration_seconds) * 1000,
        phrase_boundaries_ms=_phrase_boundaries_ms(row.phrase_boundaries_json, duration_ms),
        min_segment_ms=MIN_SEGMENT_MS,
        max_segment_ms=MAX_SEGMENT_MS,
        bpm=row.bpm,
        musical_key=row.musical_key,
        camelot=row.camelot,
    )


def _external_track_read(row: ExternalTrack) -> StudioTrackRead:
    metadata = row.provider_metadata_json or {}
    duration_ms = row.duration_sec * 1000
    return StudioTrackRead(
        source_type="audius",
        source_track_id=row.external_id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        genre=row.genre,
        vibe=metadata.get("vibe"),
        duration_ms=duration_ms,
        audio_url=_audius_audio_url(row.external_id),
        cover_url=metadata.get("cover_url"),
        analysis_status=row.analysis_status,
        suggested_start_ms=(row.segment_start_second or 0) * 1000,
        suggested_end_ms=(row.segment_end_second or min(30, row.duration_sec)) * 1000,
        phrase_boundaries_ms=_phrase_boundaries_ms(row.phrase_boundaries_json, duration_ms),
        min_segment_ms=MIN_SEGMENT_MS,
        max_segment_ms=MAX_SEGMENT_MS,
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
    # Attribution-only field (see audius_service.audius_track_page_url) --
    # carried alongside `tracks` rather than added to the generic pipeline
    # `Track` schema, which every other retriever also constructs and has
    # no notion of a provider web page.
    permalinks_by_id = {
        str(item["source_track_id"]): item.get("permalink")
        for item in raw_tracks
        if item.get("source_track_id")
    }
    existing = {
        row.external_id: row
        for row in db.query(ExternalTrack)
        .filter(ExternalTrack.source == "audius", ExternalTrack.external_id.in_(ids))
        .all()
    }
    for track in tracks:
        row = existing.get(track.source_track_id)
        metadata = {
            "tags": track.tags,
            "vibe": track.vibe,
            "cover_url": track.cover_url,
            "permalink": permalinks_by_id.get(track.source_track_id),
        }
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


def search_tracks(
    db: Session, user_id: int, q: str, source: str = "all", limit: int = 20
) -> list[StudioTrackRead]:
    """Shared search core for GET /studio/tracks/search (routers/studio.py)
    and the AI assistant's discovery turn (studio_ai_client.py::_context) --
    one implementation, so a discovery result and a manually searched-for
    track are always the exact same resolvable, addable candidates."""

    results: list[StudioTrackRead] = []
    if source in {"all", "catalog"}:
        catalog = db.query(CatalogTrack).filter(
            or_(CatalogTrack.visibility == "public", CatalogTrack.owner_id == user_id),
            CatalogTrack.duration_seconds > 0,
            CatalogTrack.analysis_status != "failed",
        )
        if q.strip():
            pattern = f"%{q.strip()}%"
            catalog = catalog.filter(
                or_(CatalogTrack.title.ilike(pattern), CatalogTrack.artist.ilike(pattern))
            )
        results.extend(
            _catalog_track_read(row) for row in catalog.order_by(CatalogTrack.id.desc()).limit(limit)
        )
    if source in {"all", "audius"} and q.strip() and len(results) < limit:
        raw = audius_service.search_tracks(q.strip(), limit=limit - len(results))
        results.extend(_external_track_read(row) for row in _remember_audius_results(db, raw))
    return results[:limit]


def resolve_track(db: Session, user_id: int, source_type: str, source_track_id: str):
    """Resolve a canonical, authorized source without trusting browser metadata."""

    if source_type == "catalog":
        try:
            track_id = int(source_track_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Track not found.") from None
        row = db.get(CatalogTrack, track_id)
        if row is None or not _catalog_accessible(row, user_id):
            raise HTTPException(status_code=404, detail="Track not found.")
        if row.duration_seconds <= 0 or row.analysis_status == "failed":
            raise HTTPException(status_code=422, detail="Track audio is not ready for Studio.")
        path = upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / row.storage_name
        if not path.is_file():
            raise HTTPException(status_code=422, detail="Track audio is unavailable.")
        return row, _catalog_track(row)

    row = (
        db.query(ExternalTrack)
        .filter(ExternalTrack.source == "audius", ExternalTrack.external_id == source_track_id)
        .first()
    )
    if row is None or row.duration_sec <= 0:
        raise HTTPException(
            status_code=404,
            detail="Open the Audius track from Studio search before saving a segment.",
        )
    if row.analysis_status == "failed" and row.analysis_attempt_count > 0:
        raise HTTPException(status_code=422, detail="Track audio failed validation.")
    return row, _external_track(row)


def validate_bounds(start_ms: int, end_ms: int, track_duration_ms: int) -> None:
    if start_ms < 0 or end_ms <= start_ms or end_ms > track_duration_ms:
        raise HTTPException(
            status_code=422,
            detail="Segment bounds must satisfy 0 <= start < end <= track duration.",
        )
    duration = end_ms - start_ms
    if duration < MIN_SEGMENT_MS or duration > MAX_SEGMENT_MS:
        raise HTTPException(
            status_code=422,
            detail=f"Segment duration must be between {MIN_SEGMENT_MS} and {MAX_SEGMENT_MS} ms.",
        )


def _selected(track: Track, row, start_ms: int, end_ms: int) -> SelectedSegment:
    return SelectedSegment(
        track=track,
        start_second=start_ms // 1000,
        end_second=math.ceil(end_ms / 1000),
        start_ms=start_ms,
        end_ms=end_ms,
        method="chorus_detection",
        bpm=row.bpm,
        bpm_confidence=row.bpm_confidence,
        musical_key=row.musical_key,
        key_mode=row.key_mode,
        camelot=row.camelot,
        key_confidence=row.key_confidence,
        phrase_boundaries=row.phrase_boundaries_json,
        integrated_loudness_lufs=row.integrated_loudness_lufs,
    )


def create_saved_segment(db: Session, user_id: int, request) -> SavedSegment:
    source_row, track = resolve_track(
        db, user_id, request.source_type, request.source_track_id
    )
    duration_ms = track.duration_seconds * 1000
    validate_bounds(request.start_ms, request.end_ms, duration_ms)
    valid, reason = audio_renderer.validate_selected_segment(
        _selected(track, source_row, request.start_ms, request.end_ms)
    )
    if not valid:
        raise HTTPException(
            status_code=422,
            detail=f"Selected audio is not playable ({reason or 'validation_failed'}).",
        )
    row = SavedSegment(
        user_id=user_id,
        source_type=request.source_type,
        source_track_id=request.source_track_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        genre=track.genre,
        vibe=track.vibe_label or track.vibe,
        source_audio_url=(
            _catalog_audio_url(source_row.id)
            if request.source_type == "catalog"
            else _audius_audio_url(source_row.external_id)
        ),
        cover_url=track.cover_url,
        track_duration_ms=duration_ms,
        start_ms=request.start_ms,
        end_ms=request.end_ms,
        label=request.label,
        created_from=request.created_from,
        **_analysis_values(source_row),
    )
    db.add(row)
    db.flush()
    db.add(
        StudioBehaviorEvent(
            user_id=user_id, event_type="segment_save", saved_segment_id=row.id
        )
    )
    db.commit()
    db.refresh(row)
    return row


def list_saved_segments(db: Session, user_id: int, query: str = "") -> list[SavedSegment]:
    rows = db.query(SavedSegment).filter(SavedSegment.user_id == user_id)
    if query.strip():
        pattern = f"%{query.strip()}%"
        rows = rows.filter(
            or_(
                SavedSegment.label.ilike(pattern),
                SavedSegment.title.ilike(pattern),
                SavedSegment.artist.ilike(pattern),
            )
        )
    return rows.order_by(SavedSegment.updated_at.desc(), SavedSegment.id.desc()).all()


def owned_segment(db: Session, user_id: int, segment_id: int) -> SavedSegment:
    row = (
        db.query(SavedSegment)
        .filter(SavedSegment.id == segment_id, SavedSegment.user_id == user_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Saved segment not found.")
    return row


def _prepare_saved_segment_update(
    db: Session,
    row: SavedSegment,
    *,
    start_ms: int,
    end_ms: int,
    label: str | None = None,
) -> None:
    validate_bounds(start_ms, end_ms, row.track_duration_ms)
    if start_ms != row.start_ms or end_ms != row.end_ms:
        source_row, track = resolve_track(
            db, row.user_id, row.source_type, row.source_track_id
        )
        valid, reason = audio_renderer.validate_selected_segment(
            _selected(track, source_row, start_ms, end_ms)
        )
        if not valid:
            raise HTTPException(
                status_code=422,
                detail=f"Selected audio is not playable ({reason or 'validation_failed'}).",
            )
    row.start_ms = start_ms
    row.end_ms = end_ms
    if label is not None:
        row.label = label
    row.updated_at = utc_now()


def update_saved_segment(db: Session, row: SavedSegment, request) -> SavedSegment:
    start_ms = request.start_ms if request.start_ms is not None else row.start_ms
    end_ms = request.end_ms if request.end_ms is not None else row.end_ms
    _prepare_saved_segment_update(
        db, row, start_ms=start_ms, end_ms=end_ms, label=request.label
    )
    db.commit()
    db.refresh(row)
    return row


def _owned_studio_mix(db: Session, user_id: int, mix_id: int) -> Mix:
    row = (
        db.query(Mix)
        .options(selectinload(Mix.segments))
        .filter(Mix.id == mix_id, Mix.owner_id == user_id, Mix.is_studio.is_(True))
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Studio mix not found.")
    return row


def owned_studio_mix(db: Session, user_id: int, mix_id: int) -> Mix:
    return _owned_studio_mix(db, user_id, mix_id)


def _require_draft(mix: Mix) -> None:
    if mix.status == "published":
        raise HTTPException(
            status_code=409,
            detail="Published Studio versions are immutable. Duplicate it to continue editing.",
        )


def _require_revision(mix: Mix, expected_revision: int) -> None:
    if mix.revision != expected_revision:
        raise HTTPException(
            status_code=409,
            detail={"message": "Draft changed in another tab.", "current_revision": mix.revision},
        )


def _touch(mix: Mix) -> None:
    mix.revision += 1
    mix.updated_at = utc_now()
    mix.render_status = "stale" if mix.rendered_revision is not None else "not_rendered"


def create_studio_mix(db: Session, user_id: int, title: str, description: str | None) -> Mix:
    mix = Mix(
        session_id=f"studio_{uuid4().hex}",
        owner_id=user_id,
        title=title,
        prompt="Manual CueMix Studio draft",
        description=description,
        status="draft",
        is_studio=True,
        revision=1,
        render_status="not_rendered",
        visibility="private",
    )
    db.add(mix)
    db.commit()
    return _owned_studio_mix(db, user_id, mix.id)


def list_studio_mixes(db: Session, user_id: int) -> list[Mix]:
    return (
        db.query(Mix)
        .options(selectinload(Mix.segments))
        .filter(Mix.owner_id == user_id, Mix.is_studio.is_(True))
        .order_by(Mix.updated_at.desc(), Mix.id.desc())
        .all()
    )


def update_studio_mix(db: Session, mix: Mix, request) -> Mix:
    _require_draft(mix)
    _require_revision(mix, request.expected_revision)
    if request.title is not None:
        mix.title = request.title
    if request.description is not None:
        mix.description = request.description
    _touch(mix)
    db.commit()
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def _snapshot(mix: Mix, saved: SavedSegment, position: int) -> MixSegment:
    return MixSegment(
        mix_id=mix.id,
        saved_segment_id=saved.id,
        position=position,
        title=saved.title,
        artist=saved.artist,
        audio_url=saved.source_audio_url,
        source_audio_url=saved.source_audio_url,
        cover_url=saved.cover_url,
        start_second=saved.start_ms // 1000,
        end_second=math.ceil(saved.end_ms / 1000),
        source_start_ms=saved.start_ms,
        source_end_ms=saved.end_ms,
        transition_to_next="end",
        transition_type="cut",
        transition_duration_ms=0,
        source=saved.source_type,
        source_track_id=saved.source_track_id,
        track_duration_seconds=math.ceil(saved.track_duration_ms / 1000),
        genre=saved.genre,
        vibe=saved.vibe,
        bpm=saved.bpm,
        musical_key=saved.musical_key,
        key_mode=saved.key_mode,
        camelot=saved.camelot,
    )


def _mix_segment_to_selected(db: Session, item: MixSegment) -> SelectedSegment:
    local_path = None
    catalog_id = None
    if item.source == "catalog":
        catalog_id = int(item.source_track_id)
        row = db.get(CatalogTrack, catalog_id)
        if row is None:
            raise HTTPException(status_code=422, detail="A source track no longer exists.")
        local_path = str(upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / row.storage_name)
    track = Track(
        source=item.source,
        source_track_id=item.source_track_id,
        title=item.title,
        artist=item.artist,
        audio_url=(
            audius_service.audius_stream_url(item.source_track_id)
            if item.source == "audius"
            else item.source_audio_url or item.audio_url
        ),
        cover_url=item.cover_url,
        duration_seconds=item.track_duration_seconds or item.end_second,
        genre=item.genre,
        vibe=item.vibe,
        catalog_track_id=catalog_id,
        local_path=local_path,
    )
    return SelectedSegment(
        track=track,
        start_second=item.source_start_ms // 1000 if item.source_start_ms is not None else 0,
        end_second=(
            math.ceil(item.source_end_ms / 1000)
            if item.source_end_ms is not None
            else max(1, item.end_second - item.start_second)
        ),
        start_ms=item.source_start_ms,
        end_ms=item.source_end_ms,
        method="chorus_detection",
        bpm=item.bpm,
        musical_key=item.musical_key,
        key_mode=item.key_mode,
        camelot=item.camelot,
        key_confidence=1.0 if item.musical_key else None,
    )


def _compatibility(previous: SelectedSegment, current: SelectedSegment, plan: TransitionPlan) -> dict:
    tempo = (
        max(0, round(100 - abs(previous.bpm - current.bpm) * 5))
        if previous.bpm is not None and current.bpm is not None
        else 50
    )
    key = {
        "same_key": 100,
        "relative": 92,
        "adjacent_camelot": 86,
        "compatible_fifth": 78,
        "conflicting": 25,
        None: 50,
    }[plan.key_category]
    energy = 100 if previous.track.vibe and previous.track.vibe == current.track.vibe else 60
    phrase = 100 if plan.phrase_aligned is True else 25 if plan.phrase_aligned is False else 50
    score = round(tempo * 0.35 + key * 0.3 + energy * 0.2 + phrase * 0.15)
    return {"score": score, "tempo": tempo, "key": key, "energy": energy, "phrase": phrase}


def recompute_transitions(
    db: Session, mix: Mix, planner: TransitionPlanner, *, preserve_types: bool = False
) -> None:
    items = sorted(mix.segments, key=lambda item: item.position)
    for index, item in enumerate(items):
        if index == len(items) - 1:
            item.transition_to_next = "end"
            item.transition_type = "cut"
            item.transition_duration_ms = 0
            item.compatibility_score = None
            item.compatibility_factors_json = None
            continue
        previous = _mix_segment_to_selected(db, item)
        current = _mix_segment_to_selected(db, items[index + 1])
        plan = planner.plan(previous, current, prefers_smoother=False)
        factors = _compatibility(previous, current, plan)
        if not preserve_types:
            item.transition_type = plan.style
            item.transition_duration_ms = plan.crossfade_ms
        item.transition_to_next = item.transition_type
        item.compatibility_score = factors["score"]
        item.compatibility_factors_json = {k: v for k, v in factors.items() if k != "score"}


def _insert_segment_item(
    db: Session, mix: Mix, saved: SavedSegment, insert_after_item_id: int | None = None
) -> MixSegment:
    """Core insertion only -- no draft/revision/commit side effects, so both
    the public `add_saved_segment` (its own commit) and `apply_assistant_plan`
    (one commit for the whole plan) can share it. `insert_after_item_id`
    places the new item immediately after that existing item; None appends
    to the end (the only behavior before this existed, so every manual-UI
    caller is unaffected)."""

    if len(mix.segments) >= MAX_STUDIO_MIX_SEGMENTS:
        raise HTTPException(status_code=422, detail="Studio mix is full.")
    if insert_after_item_id is None:
        item = _snapshot(mix, saved, len(mix.segments) + 1)
        db.add(item)
        db.flush()
    else:
        anchor = next((row for row in mix.segments if row.id == insert_after_item_id), None)
        if anchor is None:
            raise HTTPException(
                status_code=422, detail="insert_after_item_id was not found in this mix."
            )
        for row in mix.segments:
            if row.position > anchor.position:
                row.position += 1
        db.flush()
        item = _snapshot(mix, saved, anchor.position + 1)
        db.add(item)
        db.flush()
    db.refresh(mix)
    return item


def add_saved_segment(
    db: Session,
    mix: Mix,
    saved: SavedSegment,
    expected_revision: int,
    planner: TransitionPlanner,
    *,
    insert_after_item_id: int | None = None,
) -> Mix:
    _require_draft(mix)
    _require_revision(mix, expected_revision)
    _insert_segment_item(db, mix, saved, insert_after_item_id)
    recompute_transitions(db, mix, planner)
    _touch(mix)
    db.commit()
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def reorder_mix(
    db: Session, mix: Mix, segment_ids: list[int], expected_revision: int, planner
) -> Mix:
    _require_draft(mix)
    _require_revision(mix, expected_revision)
    current_ids = [item.id for item in mix.segments]
    if len(segment_ids) != len(set(segment_ids)) or set(segment_ids) != set(current_ids):
        raise HTTPException(status_code=422, detail="Reorder must contain every item exactly once.")
    _apply_mix_order(db, mix, segment_ids)
    recompute_transitions(db, mix, planner)
    _touch(mix)
    db.commit()
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def _apply_mix_order(db: Session, mix: Mix, segment_ids: list[int]) -> None:
    by_id = {item.id: item for item in mix.segments}
    # Move through temporary negative positions so the unique constraint is
    # never violated mid-flush on PostgreSQL or SQLite.
    for index, item in enumerate(mix.segments, start=1):
        item.position = -index
    db.flush()
    for position, item_id in enumerate(segment_ids, start=1):
        by_id[item_id].position = position
    db.flush()
    db.refresh(mix)


def _remove_segment_items(db: Session, mix: Mix, item_ids: set[int]) -> None:
    """Core removal only -- no draft/revision/commit side effects, shared
    the same way _insert_segment_item is; see that function's docstring."""

    existing_ids = {row.id for row in mix.segments}
    missing = item_ids - existing_ids
    if missing:
        raise HTTPException(status_code=404, detail="Mix item not found.")
    for item in list(mix.segments):
        if item.id in item_ids:
            db.delete(item)
    db.flush()
    remaining = sorted(
        (row for row in mix.segments if row.id not in item_ids), key=lambda row: row.position
    )
    for position, row in enumerate(remaining, start=1):
        row.position = position
    db.flush()
    db.refresh(mix)


def remove_mix_item(
    db: Session, mix: Mix, item_id: int, expected_revision: int, planner
) -> Mix:
    _require_draft(mix)
    _require_revision(mix, expected_revision)
    _remove_segment_items(db, mix, {item_id})
    recompute_transitions(db, mix, planner)
    _touch(mix)
    db.commit()
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def update_transition(db: Session, mix: Mix, item_id: int, request, planner) -> Mix:
    _require_draft(mix)
    _require_revision(mix, request.expected_revision)
    item = next((row for row in mix.segments if row.id == item_id), None)
    if item is None or item.position == len(mix.segments):
        raise HTTPException(status_code=422, detail="This item has no following transition.")
    item.transition_type = request.transition_type
    item.transition_duration_ms = 0 if request.transition_type == "cut" else request.duration_ms
    recompute_transitions(db, mix, planner, preserve_types=True)
    _touch(mix)
    db.commit()
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def _item_duration_ms(item: MixSegment) -> int:
    return max(0, (item.source_end_ms or 0) - (item.source_start_ms or 0))


def _mix_duration_ms(mix: Mix) -> int:
    """Same duration formula studio_ai_client._plan_calculations uses (sum of
    selected segment durations minus effective non-cut overlap) -- kept as
    its own small copy rather than a shared import to avoid a
    studio_service <-> studio_ai_client import cycle (studio_ai_client
    already imports this module). Computed here off the mix's *actual*,
    already-mutated segments, post-plan, for active_constraints enforcement
    (see apply_assistant_plan's own docstring)."""

    items = sorted(mix.segments, key=lambda row: row.position)
    overlap_ms = 0
    for index, item in enumerate(items[:-1]):
        following = items[index + 1]
        if item.transition_type != "cut":
            overlap_ms += max(
                0,
                min(
                    item.transition_duration_ms,
                    max(0, _item_duration_ms(item) - 1),
                    max(0, _item_duration_ms(following) - 1),
                ),
            )
    return max(0, sum(_item_duration_ms(item) for item in items) - overlap_ms)


def _enforce_active_constraints(mix: Mix, request) -> None:
    """Mechanically enforces only the constraints the *frontend* is tracking
    client-side and passes explicitly as structured data (request.
    active_constraints) -- never anything parsed from remembered_constraints
    free text server-side. See cuemix-studio-ai-v2-spec.md §9.3."""

    remaining_ids = {item.id for item in mix.segments}
    for constraint in request.active_constraints:
        if constraint.type == "keep_item":
            if constraint.item_id not in remaining_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"This plan removes item {constraint.item_id}, which is pinned to stay in the mix.",
                )
        elif constraint.type == "max_duration_ms":
            if _mix_duration_ms(mix) > constraint.value_ms:
                raise HTTPException(
                    status_code=422,
                    detail=f"This plan would exceed the pinned {constraint.value_ms}ms mix duration limit.",
                )


def apply_assistant_plan(db: Session, user_id: int, request, planner):
    """Validate and atomically apply a user-confirmed bounded assistant plan.

    Order of operations, all within one transaction (a single commit at the
    end): remove pinned items first, then add a new one, then validate/apply
    reorder and transition changes against the mix as it now stands -- this
    matches how a human editing the draft in one sitting would experience
    several changes made together, and keeps every downstream validation
    (proposed_order's "every current item exactly once", a transition's
    target existing) reasoning about one consistent, already-updated set of
    items rather than the pre-plan one."""

    mix = None
    saved = None
    has_actual_change = False
    has_mix_changes = (
        request.proposed_order is not None
        or bool(request.transition_changes)
        or bool(request.removed_item_ids)
        or request.add_item is not None
    )
    if has_mix_changes:
        mix = owned_studio_mix(db, user_id, request.mix_id)
        _require_draft(mix)
        _require_revision(mix, request.expected_revision)

        if request.removed_item_ids:
            _remove_segment_items(db, mix, set(request.removed_item_ids))
            has_actual_change = True

        if request.add_item is not None:
            add = request.add_item
            if add.source_type == "saved_segment":
                segment_for_add = owned_segment(db, user_id, add.saved_segment_id)
            else:
                # A partial-commit tradeoff, accepted deliberately:
                # create_saved_segment commits its own SavedSegment row
                # immediately (see that function), before the rest of this
                # plan is applied/committed. If a later step in this same
                # plan fails, the new saved segment stays committed but
                # simply unattached to any mix -- identical in effect to a
                # user manually creating one via POST /studio/segments and
                # then deciding not to add it, never a corrupted mix state.
                segment_for_add = create_saved_segment(
                    db,
                    user_id,
                    SavedSegmentCreate(
                        source_type=add.source_type,
                        source_track_id=add.source_track_id,
                        start_ms=add.start_ms,
                        end_ms=add.end_ms,
                        label=f"AI pick for {mix.title}"[:120],
                        created_from="ai",
                    ),
                )
            _insert_segment_item(db, mix, segment_for_add, add.insert_after_item_id)
            has_actual_change = True

        current_ids = {item.id for item in mix.segments}
        if request.proposed_order is not None and (
            len(request.proposed_order) != len(set(request.proposed_order))
            or set(request.proposed_order) != current_ids
        ):
            raise HTTPException(
                status_code=422,
                detail="Assistant order must contain every current item exactly once.",
            )
        effective_order = request.proposed_order or [
            item.id for item in sorted(mix.segments, key=lambda row: row.position)
        ]
        current_order = [
            item.id for item in sorted(mix.segments, key=lambda row: row.position)
        ]
        transition_ids = [change.item_id for change in request.transition_changes]
        if len(transition_ids) != len(set(transition_ids)):
            raise HTTPException(
                status_code=422,
                detail="An assistant plan may change each transition only once.",
            )
        for change in request.transition_changes:
            if change.item_id not in current_ids or effective_order[-1] == change.item_id:
                raise HTTPException(
                    status_code=422,
                    detail="Assistant transition must target an item with a following item.",
                )
            if change.transition_type == "cut" and change.duration_ms != 0:
                raise HTTPException(
                    status_code=422, detail="A cut transition must have zero duration."
                )
        by_id = {item.id: item for item in mix.segments}
        has_actual_change = has_actual_change or effective_order != current_order or any(
            change.transition_type != by_id[change.item_id].transition_type
            or change.duration_ms != by_id[change.item_id].transition_duration_ms
            for change in request.transition_changes
        )

    if request.segment_bound_change is not None:
        bound = request.segment_bound_change
        saved = owned_segment(db, user_id, bound.candidate_id)
        has_actual_change = has_actual_change or (
            bound.proposed_start_ms != saved.start_ms
            or bound.proposed_end_ms != saved.end_ms
        )
        _prepare_saved_segment_update(
            db,
            saved,
            start_ms=bound.proposed_start_ms,
            end_ms=bound.proposed_end_ms,
        )

    if not has_actual_change:
        raise HTTPException(
            status_code=422, detail="Assistant plan does not change the current draft."
        )

    if mix is not None:
        structural_change = (
            request.proposed_order is not None
            or bool(request.removed_item_ids)
            or request.add_item is not None
        )
        if request.proposed_order is not None:
            _apply_mix_order(db, mix, request.proposed_order)
        if structural_change:
            recompute_transitions(db, mix, planner)
        by_id = {item.id: item for item in mix.segments}
        for change in request.transition_changes:
            item = by_id[change.item_id]
            item.transition_type = change.transition_type
            item.transition_duration_ms = (
                0 if change.transition_type == "cut" else change.duration_ms
            )
        if request.transition_changes:
            recompute_transitions(db, mix, planner, preserve_types=True)
        if request.active_constraints:
            _enforce_active_constraints(mix, request)
        _touch(mix)

    db.commit()
    applied_mix = _owned_studio_mix(db, user_id, mix.id) if mix is not None else None
    if saved is not None:
        db.refresh(saved)
    return applied_mix, saved


def _persisted_transition(item: MixSegment) -> TransitionPlan:
    style = item.transition_type
    return TransitionPlan(
        crossfade_ms=0 if style == "cut" else item.transition_duration_ms,
        style=style,
        notes="User-selected Studio transition.",
    )


def render_mix(
    db: Session,
    mix: Mix,
    renderer: AudioRenderer,
    *,
    expected_revision: int | None = None,
) -> Mix:
    _require_draft(mix)
    if not mix.segments:
        raise HTTPException(status_code=422, detail="Add at least one saved segment first.")
    target_revision = mix.revision if expected_revision is None else expected_revision
    if mix.revision != target_revision:
        return mix
    mix.render_status = "rendering"
    db.commit()
    try:
        items = sorted(mix.segments, key=lambda item: item.position)
        selected = [_mix_segment_to_selected(db, item) for item in items]
        transitions = [_persisted_transition(item) for item in items[:-1]]
        rendered = renderer.render(selected, transitions)
        if rendered.is_pass_through and len(items) > 1:
            raise HTTPException(
                status_code=422,
                detail="Full mix rendering failed; no incomplete pass-through was saved.",
            )
        # A draft may be edited while rendering. Re-read its concurrency
        # fields and never attach an obsolete artifact to the newer draft.
        db.refresh(mix, attribute_names=["revision", "render_status"])
        if mix.revision != target_revision or mix.render_status != "rendering":
            mix.render_status = "stale"
            db.commit()
            return _owned_studio_mix(db, mix.owner_id, mix.id)
        for item, offsets in zip(items, rendered.offsets):
            item.audio_url = rendered.audio_url
            item.start_second, item.end_second = offsets
        mix.rendered_audio_url = rendered.audio_url
        mix.rendered_revision = mix.revision
        mix.render_status = "ready"
        db.commit()
    except Exception:
        db.rollback()
        mix = _owned_studio_mix(db, mix.owner_id, mix.id)
        mix.render_status = "failed"
        db.commit()
        raise
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def enqueue_render_mix(db: Session, mix: Mix) -> Mix:
    """Persist render intent, then dispatch the exact revision to the shared queue."""

    _require_draft(mix)
    if not mix.segments:
        raise HTTPException(status_code=422, detail="Add at least one saved segment first.")
    if mix.render_status == "rendering":
        return mix
    mix.render_status = "rendering"
    db.commit()
    try:
        upload_queue.upload_queue.submit_studio_render(
            mix.id, mix.owner_id, mix.revision
        )
    except Full:
        mix.render_status = "failed"
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="The media queue is full; try rendering again shortly.",
        ) from None
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def requeue_pending_studio_renders() -> int:
    """Recover render intents that survived an unclean backend restart."""

    from app.database import database as db_module

    queued = 0
    with db_module.SessionLocal() as db:
        pending = (
            db.query(Mix)
            .filter(
                Mix.is_studio.is_(True),
                Mix.status == "draft",
                Mix.render_status == "rendering",
            )
            .all()
        )
        for mix in pending:
            try:
                upload_queue.upload_queue.submit_studio_render(
                    mix.id, mix.owner_id, mix.revision
                )
                queued += 1
            except Full:
                mix.render_status = "failed"
        db.commit()
    return queued


def preview_transition(
    db: Session, mix: Mix, item_id: int, renderer: AudioRenderer
) -> str:
    items = sorted(mix.segments, key=lambda item: item.position)
    index = next((i for i, item in enumerate(items) if item.id == item_id), -1)
    if index < 0 or index >= len(items) - 1:
        raise HTTPException(status_code=422, detail="Transition preview is unavailable.")
    rendered = renderer.render(
        [_mix_segment_to_selected(db, items[index]), _mix_segment_to_selected(db, items[index + 1])],
        [_persisted_transition(items[index])],
    )
    if rendered.is_pass_through:
        raise HTTPException(status_code=422, detail="Transition preview could not be rendered.")
    return rendered.audio_url


def publish_mix(db: Session, mix: Mix) -> Mix:
    """Studio's own draft/render-ready/concurrency gate, then the same
    rights-check + mode-selection + manifest-building policy a regular
    generated mix's publish uses -- see publish_service.py's own module
    docstring. A provider-sourced Studio draft is no longer rejected here:
    it publishes as an immutable `provider_manifest` instead of a
    `rendered_asset`, exactly like a provider-backed regular mix does."""

    _require_draft(mix)
    if mix.render_status != "ready" or mix.rendered_revision != mix.revision:
        raise HTTPException(status_code=409, detail="Render the current draft revision before publishing.")
    publish_service.publish_mix(db, mix)
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def duplicate_mix(db: Session, mix: Mix, user_id: int) -> Mix:
    duplicate = create_studio_mix(
        db, user_id, f"{mix.title} — new draft", mix.description
    )
    for source in sorted(mix.segments, key=lambda item: item.position):
        duplicate.segments.append(
            MixSegment(
                mix_id=duplicate.id,
                position=source.position,
                saved_segment_id=source.saved_segment_id,
                title=source.title,
                artist=source.artist,
                audio_url=source.source_audio_url or source.audio_url,
                source_audio_url=source.source_audio_url,
                cover_url=source.cover_url,
                start_second=source.source_start_ms // 1000,
                end_second=math.ceil(source.source_end_ms / 1000),
                source_start_ms=source.source_start_ms,
                source_end_ms=source.source_end_ms,
                transition_to_next=source.transition_to_next,
                transition_type=source.transition_type,
                transition_duration_ms=source.transition_duration_ms,
                source=source.source,
                source_track_id=source.source_track_id,
                track_duration_seconds=source.track_duration_seconds,
                genre=source.genre,
                vibe=source.vibe,
                bpm=source.bpm,
                musical_key=source.musical_key,
                key_mode=source.key_mode,
                camelot=source.camelot,
                compatibility_score=source.compatibility_score,
                compatibility_factors_json=source.compatibility_factors_json,
            )
        )
    db.commit()
    return _owned_studio_mix(db, user_id, duplicate.id)


def record_behavior(db: Session, user_id: int, request) -> StudioBehaviorEvent:
    if request.saved_segment_id is not None:
        owned_segment(db, user_id, request.saved_segment_id)
    if request.mix_id is not None:
        mix = db.get(Mix, request.mix_id)
        if mix is None:
            raise HTTPException(status_code=404, detail="Mix not found.")
    if request.saved_segment_id is None and request.mix_id is None:
        raise HTTPException(status_code=422, detail="A segment or mix is required.")
    event = StudioBehaviorEvent(
        user_id=user_id,
        event_type=request.event_type,
        saved_segment_id=request.saved_segment_id,
        mix_id=request.mix_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def behavior_signals(db: Session, user_id: int) -> dict[int, dict]:
    segments = list_saved_segments(db, user_id)
    cutoff = utc_now() - timedelta(days=365)
    events = (
        db.query(StudioBehaviorEvent)
        .filter(
            StudioBehaviorEvent.user_id == user_id,
            StudioBehaviorEvent.created_at >= cutoff,
            StudioBehaviorEvent.saved_segment_id.is_not(None),
        )
        .all()
    )
    grouped: dict[int, dict[str, float]] = {}
    now = utc_now()
    for event in events:
        age_days = max(0.0, (now - event.created_at).total_seconds() / 86400)
        weight = 0.5 ** (age_days / 90.0)
        bucket = grouped.setdefault(event.saved_segment_id, {})
        bucket[event.event_type] = bucket.get(event.event_type, 0.0) + weight

    liked_counts = dict(
        db.query(MixSegment.saved_segment_id, func.count(MixLike.id))
        .join(MixLike, MixLike.mix_id == MixSegment.mix_id)
        .filter(MixSegment.saved_segment_id.is_not(None))
        .group_by(MixSegment.saved_segment_id)
        .all()
    )
    result = {}
    for segment in segments:
        values = grouped.get(segment.id, {})
        save = min(0.15, 0.08 * math.sqrt(values.get("segment_save", 0.0)))
        replay = 0.12 * (1 - math.exp(-values.get("segment_replay", 0.0) / 3))
        skip = 0.18 * (1 - math.exp(-values.get("early_skip", 0.0) / 3))
        like = min(0.08, 0.03 * math.log1p(liked_counts.get(segment.id, 0)))
        total = max(-0.25, min(0.35, save + replay + like - skip))
        result[segment.id] = {
            "saved_segment_id": segment.id,
            "save_score": round(save, 4),
            "replay_score": round(replay, 4),
            "like_score": round(like, 4),
            "skip_penalty": round(skip, 4),
            "total_adjustment": round(total, 4),
        }
    return result


def _intent_score(segment: SavedSegment, intent: PromptIntent) -> float:
    score = 0.0
    genre = (segment.genre or "").casefold()
    vibe = (segment.vibe or "").casefold()
    if genre and any(term.casefold() in genre for term in intent.genres):
        score += 0.35
    if intent.mood.casefold() in vibe:
        score += 0.2
    if intent.energy == "high" and any(term in vibe for term in ("energy", "party", "upbeat")):
        score += 0.15
    if intent.energy == "low" and any(term in vibe for term in ("calm", "chill", "soft")):
        score += 0.15
    return score


def auto_mix_from_saved(
    db: Session,
    user_id: int,
    request,
    vibe: VibeUnderstander,
    planner: TransitionPlanner,
) -> Mix:
    segments = list_saved_segments(db, user_id)
    if not segments:
        raise HTTPException(status_code=422, detail="Save at least one segment first.")
    intent = apply_auto_mix_mode(vibe.understand(request.prompt), request.mode)
    signals = behavior_signals(db, user_id)
    ranked = sorted(
        segments,
        key=lambda segment: (
            -(_intent_score(segment, intent) + signals[segment.id]["total_adjustment"]),
            segment.id,
        ),
    )[: request.limit]
    mix = create_studio_mix(db, user_id, request.title, "Auto-mixed from saved segments")
    mix.prompt = request.prompt
    mix.mode = request.mode.value if isinstance(request.mode, AutoMixMode) else None
    for position, saved in enumerate(ranked, start=1):
        db.add(_snapshot(mix, saved, position))
    db.flush()
    db.refresh(mix)
    recompute_transitions(db, mix, planner)
    db.commit()
    return _owned_studio_mix(db, user_id, mix.id)
