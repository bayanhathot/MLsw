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
    SelectedSegment,
    Track,
    TransitionPlan,
)
from app.services import audius_service, upload_queue
from app.services.pipeline import audio_renderer
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


def update_saved_segment(db: Session, row: SavedSegment, request) -> SavedSegment:
    start_ms = request.start_ms if request.start_ms is not None else row.start_ms
    end_ms = request.end_ms if request.end_ms is not None else row.end_ms
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
    if request.label is not None:
        row.label = request.label
    row.updated_at = utc_now()
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


def add_saved_segment(
    db: Session,
    mix: Mix,
    saved: SavedSegment,
    expected_revision: int,
    planner: TransitionPlanner,
) -> Mix:
    _require_draft(mix)
    _require_revision(mix, expected_revision)
    if len(mix.segments) >= MAX_STUDIO_MIX_SEGMENTS:
        raise HTTPException(status_code=422, detail="Studio mix is full.")
    item = _snapshot(mix, saved, len(mix.segments) + 1)
    db.add(item)
    db.flush()
    db.refresh(mix)
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
    recompute_transitions(db, mix, planner)
    _touch(mix)
    db.commit()
    return _owned_studio_mix(db, mix.owner_id, mix.id)


def remove_mix_item(
    db: Session, mix: Mix, item_id: int, expected_revision: int, planner
) -> Mix:
    _require_draft(mix)
    _require_revision(mix, expected_revision)
    item = next((row for row in mix.segments if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Mix item not found.")
    db.delete(item)
    db.flush()
    remaining = sorted((row for row in mix.segments if row.id != item_id), key=lambda row: row.position)
    for position, row in enumerate(remaining, start=1):
        row.position = position
    db.flush()
    db.refresh(mix)
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
    _require_draft(mix)
    if mix.render_status != "ready" or mix.rendered_revision != mix.revision:
        raise HTTPException(status_code=409, detail="Render the current draft revision before publishing.")
    # Audius permits streaming through its provider endpoint, not republishing
    # downloaded bytes as a new public asset. Keep such Studio drafts private.
    if any(item.source != "catalog" for item in mix.segments):
        raise HTTPException(
            status_code=422,
            detail="Provider-sourced segments can be edited privately but cannot be republished.",
        )
    catalog_ids = {int(item.source_track_id) for item in mix.segments}
    catalog_rows = {
        row.id: row
        for row in db.query(CatalogTrack).filter(CatalogTrack.id.in_(catalog_ids)).all()
    }
    if len(catalog_rows) != len(catalog_ids) or any(
        catalog_rows[track_id].owner_id not in {None, mix.owner_id}
        for track_id in catalog_ids
    ):
        raise HTTPException(
            status_code=422,
            detail="Only your own uploads and bundled demo tracks can be published.",
        )
    mix.status = "published"
    mix.visibility = "public"
    mix.published_at = utc_now()
    mix.published_revision = mix.revision
    mix.published_audio_url = mix.rendered_audio_url
    mix.published_segments_json = [
        {
            "id": item.id,
            "position": item.position,
            "title": item.title,
            "artist": item.artist,
            "source": item.source,
            "source_track_id": item.source_track_id,
            "source_start_ms": item.source_start_ms,
            "source_end_ms": item.source_end_ms,
            "transition_type": item.transition_type,
            "transition_duration_ms": item.transition_duration_ms,
        }
        for item in sorted(mix.segments, key=lambda item: item.position)
    ]
    db.commit()
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
