"""Additive real-catalog upload: album/artist/title are required alongside
the audio file (lyrics and cover art stay optional -- instrumental tracks
are first-class, see ai-dj-segment-metadata-architecture.md §3), validated
server-side by the same byte-signature check attachments use, plus a deeper
decodability/silence check (see upload_queue._validate_decodable_audio).
A successful upload queues the same one-time BPM/key/best-segment analysis
job upload_queue.py already runs for step 5.

Two upload shapes share the same underlying UploadQueue (never a second job
system, per the architecture doc's ingest rules):

- POST /catalog/tracks: the original single-file path. Synchronous from the
  caller's perspective -- it waits (briefly) for the file to finish storing,
  then returns the created row directly. No job to poll; analysis still
  runs fully in the background.
- POST /catalog/tracks/batch-jobs (+ polling/retry/cancel): the bulk-upload
  path. Returns immediately with a job_id and never blocks on storage,
  validation, or analysis. The CatalogTrack row is created *eagerly* by a
  callback the moment a job's bytes finish storing (registered with
  upload_queue.register_callback below) -- not lazily on poll -- so the
  job's own status can meaningfully progress through
  queued -> validating -> storing -> analyzing -> completed/failed/
  cancelled, with a live WebSocket push (see _on_catalog_job_status_changed)
  and a terminal notification on every transition, not just a snapshot read
  at poll time. Every file in one "Upload All" batch shares a client-generated
  batch_id, which also drives fair-share priority so one huge batch can't
  starve a smaller one queued alongside it.

This is separate from POST /uploads/jobs (forum/message attachments): those
don't carry track metadata and aren't part of the AI-DJ catalog.
"""

import logging
import os
from pathlib import Path
from queue import Full
from time import monotonic, sleep
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.core.rate_limit import write_rate_limit
from app.database import database as db_module
from app.database.database import get_db
from app.database.models.catalog import CatalogTrack
from app.database.models.messaging import Notification
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import (
    CatalogBatchStatusRead,
    CatalogTrackRead,
    CatalogUploadJobRead,
    NotificationRead,
)
from app.services import upload_queue as uq
from app.services.channel_hub import sync_publish
from app.services.pipeline.catalog_retriever import CATALOG_AUDIO_SUBDIR

router = APIRouter(prefix="/catalog", tags=["catalog"])
logger = logging.getLogger(__name__)

_AUDIO_CONTENT_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/flac"}
_COVER_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_COVER_SUBDIR = "catalog_covers"
_VISIBILITIES = {"private", "public"}
_STORE_WAIT_SECONDS = 5.0
_ON_STORED_CALLBACK = "catalog_track_created"
_ANALYSIS_COMPLETE_CALLBACK = "catalog_track_analyzed"
# Every file in a batch starts at the same priority a normal single upload
# gets; every _DECAY_EVERY files deeper into the SAME batch, priority drops
# by one (floor 0). A small batch (or the first few files of a large one)
# is never penalized -- only a batch large enough to matter sinks below
# fresh single/small-batch uploads queued after it, so it can't starve them.
_BATCH_PRIORITY_BASE = 5
_BATCH_PRIORITY_DECAY_EVERY = max(1, int(os.getenv("CATALOG_BATCH_PRIORITY_DECAY_EVERY", "3")))


async def _iter_upload_file(file: UploadFile, chunk_size: int = 65536):
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        yield chunk


async def _read_limited(file: UploadFile, maximum_bytes: int) -> bytes:
    return await uq.read_limited_stream(_iter_upload_file(file), maximum_bytes)


def _priority_for_batch_position(position: int) -> int:
    return max(0, _BATCH_PRIORITY_BASE - position // _BATCH_PRIORITY_DECAY_EVERY)


def _probe_duration_seconds(path: Path) -> int:
    try:
        from pydub import AudioSegment

        return max(0, int(len(AudioSegment.from_file(path)) / 1000))
    except Exception:
        # A best-effort probe: an unreadable file still gets a catalog row
        # (duration 0) and the analysis job below will mark it "failed".
        return 0


def _wait_for_store(job_id: str) -> dict:
    """Only used by the synchronous single-file endpoint -- the bulk path
    never blocks a request on this."""

    deadline = monotonic() + _STORE_WAIT_SECONDS
    job = uq.upload_queue.public(job_id)
    while job is not None and job["status"] in {"queued", "validating", "storing"} and monotonic() < deadline:
        sleep(0.01)
        job = uq.upload_queue.public(job_id)
    if job is None or job["status"] not in {"completed", "failed"}:
        raise HTTPException(
            status_code=503, detail="Upload is taking longer than expected. Try again."
        )
    return job


async def _validate_and_store_cover(cover: UploadFile | None) -> str | None:
    """Cover art is small and decoded synchronously (unlike audio, which is
    deferred to a worker) -- validated with the same byte-signature check
    every image upload already uses. Returns None (never a fabricated
    image or an external fetch) if no cover was given; the frontend/DJ UI
    fall back to the app's existing initials placeholder in that case."""

    if cover is None or not (cover.filename or "").strip():
        return None
    content_type = (cover.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _COVER_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Cover art must be JPG, PNG, or WebP.")
    max_bytes = uq.ALLOWED_TYPES[content_type][2]
    data = await _read_limited(cover, max_bytes)
    try:
        _kind, extension, _max_size = uq.validate_upload(cover.filename or "cover", content_type, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Cover art: {exc}") from None
    target_dir = uq.UPLOAD_DIR / _COVER_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{uuid4().hex}{extension}"
    (target_dir / storage_name).write_bytes(data)
    return storage_name


def _clean_metadata_fields(
    *,
    album: str,
    artist: str,
    title: str,
    lyrics: str | None,
    genre: str | None,
    visibility: str,
    cover_storage_name: str | None = None,
) -> dict:
    album, artist, title = album.strip(), artist.strip(), title.strip()
    if not album or not artist or not title:
        raise HTTPException(status_code=422, detail="title, album, and artist are required.")
    if visibility not in _VISIBILITIES:
        raise HTTPException(status_code=422, detail="visibility must be 'private' or 'public'.")
    return {
        "album": album,
        "artist": artist,
        "title": title,
        "lyrics": lyrics.strip() if lyrics and lyrics.strip() else None,
        "genre": genre.strip() if genre and genre.strip() else None,
        "visibility": visibility,
        "cover_storage_name": cover_storage_name,
    }


def _build_catalog_track(
    *,
    owner_id: int,
    content_type: str,
    storage_name: str,
    sha256: str,
    duration_seconds: int,
    fields: dict,
) -> CatalogTrack:
    return CatalogTrack(
        owner_id=owner_id,
        title=fields["title"][:255],
        artist=fields["artist"],
        album=fields["album"],
        lyrics=fields["lyrics"],
        genre=fields["genre"],
        visibility=fields["visibility"],
        storage_name=storage_name,
        cover_storage_name=fields.get("cover_storage_name"),
        content_type=content_type,
        duration_seconds=duration_seconds,
        analysis_status="pending",
        checksum_sha256=sha256,
    )


def _dispatch_analysis(track_id: int, upload_job_id: str | None = None) -> None:
    try:
        uq.upload_queue.submit_analysis(track_id, upload_job_id=upload_job_id)
    except Full:
        logger.warning("Analysis queue is full; catalog track %s stays pending.", track_id)


def _to_read(row: CatalogTrack) -> CatalogTrackRead:
    return CatalogTrackRead(
        id=row.id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        genre=row.genre,
        lyrics=row.lyrics,
        visibility=row.visibility,
        duration_seconds=row.duration_seconds,
        analysis_status=row.analysis_status,
        audio_url=public_api_url(f"/catalog/tracks/{row.id}/audio"),
        cover_url=public_api_url(f"/catalog/tracks/{row.id}/cover") if row.cover_storage_name else None,
        created_at=row.created_at,
    )


def _job_to_read(job: dict) -> CatalogUploadJobRead:
    track = None
    if job.get("catalog_track_id") is not None:
        with db_module.SessionLocal() as db:
            row = db.query(CatalogTrack).filter_by(id=job["catalog_track_id"]).first()
            if row is not None:
                track = _to_read(row)
    return CatalogUploadJobRead(
        job_id=job["job_id"],
        batch_id=job.get("batch_id") or "",
        filename=job["filename"],
        status=job["status"],
        priority=job["priority"],
        track=track,
        error=job.get("error"),
    )


# ---------------------------------------------------------------------------
# upload_queue.py callbacks -- registered once at import time. Named (not a
# raw closure) so a job recovered after a restart can still find these by
# name; see upload_queue.register_callback's own docstring.
# ---------------------------------------------------------------------------


def _on_catalog_file_stored(job_id: str) -> None:
    """Runs on a worker thread right after a batch-upload job's bytes finish
    storing. Creates the CatalogTrack row and dispatches analysis; raising
    here makes the worker mark the job "failed" instead of silently losing
    the file."""

    job = uq.upload_queue.public(job_id)
    if job is None:
        raise RuntimeError(f"Catalog upload job {job_id} vanished before materialization.")
    result = job["result"]
    fields = job["metadata"] or {}
    storage_path = uq.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / result["storage_name"]
    duration_seconds = _probe_duration_seconds(storage_path)
    row = _build_catalog_track(
        owner_id=job["owner_id"],
        content_type=job["content_type"],
        storage_name=result["storage_name"],
        sha256=result["sha256"],
        duration_seconds=duration_seconds,
        fields=fields,
    )
    with db_module.SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        track_id = row.id
    uq.upload_queue.set_catalog_track(job_id, track_id)
    _dispatch_analysis(track_id, upload_job_id=job_id)


def _on_catalog_analysis_complete(job_id: str, catalog_track_id: int | None) -> None:
    """Fires once the upload job's associated analyze_catalog_track run
    finishes (success or failure -- either way the track itself is
    playable, see _build_catalog_track's whole-clip fallback story), i.e.
    once the upload job reaches its real terminal "completed" state. This
    is what "ready in your catalog" is actually gated on, not just "stored"."""

    job = uq.upload_queue.public(job_id)
    if job is None or catalog_track_id is None:
        return
    with db_module.SessionLocal() as db:
        track = db.query(CatalogTrack).filter_by(id=catalog_track_id).first()
        if track is None:
            return
        notification = Notification(
            recipient_id=job["owner_id"],
            actor_id=None,
            kind="catalog_upload_completed",
            message=f'"{track.title}" uploaded successfully and is ready in your catalog.',
            entity_type="catalog_track",
            entity_id=track.id,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
    payload = NotificationRead.model_validate(notification).model_dump(mode="json")
    sync_publish(f"user:{job['owner_id']}", "notification", payload)


def _on_catalog_job_status_changed(job: dict) -> None:
    """A generic upload_queue.add_status_listener hook -- fires on *every*
    status transition for *every* job (attachments included), so this
    filters to catalog jobs only (metadata is only ever set by the two
    catalog upload endpoints below) and pushes a live update onto the
    owning user's already-auto-subscribed "user:{id}" channel -- the same
    channel notifications use, no new subscription needed on the frontend.
    Also fires the failure notification here (unlike the success path,
    which waits for analysis -- a failed upload has no further step to
    wait for, so its notification fires as soon as the job itself fails)."""

    if job.get("metadata") is None and job.get("catalog_track_id") is None:
        return  # not a catalog job
    owner_channel = f"user:{job['owner_id']}"
    sync_publish(owner_channel, "catalog_job_updated", _job_to_read(job).model_dump(mode="json"))

    if job["status"] != "failed":
        return
    fields = job.get("metadata") or {}
    title = fields.get("title") or job.get("filename") or "Your upload"
    reason = job.get("error") or "an unknown error"
    with db_module.SessionLocal() as db:
        notification = Notification(
            recipient_id=job["owner_id"],
            actor_id=None,
            kind="catalog_upload_failed",
            message=f'"{title}" could not be uploaded: {reason}',
            entity_type=None,
            entity_id=None,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
    payload = NotificationRead.model_validate(notification).model_dump(mode="json")
    sync_publish(owner_channel, "notification", payload)


uq.register_callback(_ON_STORED_CALLBACK, _on_catalog_file_stored)
uq.register_analysis_complete_callback(_ANALYSIS_COMPLETE_CALLBACK, _on_catalog_analysis_complete)
uq.add_status_listener(_on_catalog_job_status_changed)


@router.post("/tracks", response_model=CatalogTrackRead, status_code=status.HTTP_201_CREATED)
async def upload_catalog_track(
    title: str = Form(..., min_length=1, max_length=255),
    album: str = Form(..., min_length=1, max_length=255),
    artist: str = Form(..., min_length=1, max_length=255),
    lyrics: str | None = Form(default=None, max_length=20_000),
    genre: str | None = Form(default=None, max_length=100),
    visibility: str = Form(default="public"),
    file: UploadFile = File(...),
    cover: UploadFile | None = File(default=None),
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cover_storage_name = await _validate_and_store_cover(cover)
    fields = _clean_metadata_fields(
        album=album, artist=artist, title=title, lyrics=lyrics, genre=genre,
        visibility=visibility, cover_storage_name=cover_storage_name,
    )

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type.")
    max_bytes = uq.CATALOG_AUDIO_MAX_BYTES[content_type]
    data = await _read_limited(file, max_bytes)
    try:
        uq.validate_upload(file.filename or "track", content_type, data, max_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    try:
        job = uq.upload_queue.submit(
            current_user.id,
            file.filename or "track",
            content_type,
            data,
            priority=5,
            storage_subdir=CATALOG_AUDIO_SUBDIR,
            max_size_override=max_bytes,
            deep_audio_validation=True,
        )
    except Full:
        raise HTTPException(status_code=503, detail="Upload queue is full. Try again later.") from None

    job = _wait_for_store(job["job_id"])
    if job["status"] == "failed":
        raise HTTPException(status_code=422, detail=job["error"] or "Upload failed validation.")

    result = job["result"]
    storage_path = uq.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / result["storage_name"]
    duration_seconds = _probe_duration_seconds(storage_path)

    row = _build_catalog_track(
        owner_id=current_user.id,
        content_type=content_type,
        storage_name=result["storage_name"],
        sha256=result["sha256"],
        duration_seconds=duration_seconds,
        fields=fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Marks the job "claimed" (see UploadQueue._is_claimed) so _prune()'s
    # unclaimed-file TTL cleanup -- built for a generic attachment nobody
    # ever attached to a post -- never deletes this CatalogTrack's audio out
    # from under it once that TTL elapses.
    uq.upload_queue.set_catalog_track(job["job_id"], row.id)
    _dispatch_analysis(row.id)

    return _to_read(row)


@router.post(
    "/tracks/batch-jobs", response_model=CatalogUploadJobRead, status_code=status.HTTP_202_ACCEPTED
)
async def enqueue_catalog_track(
    batch_id: str = Form(..., min_length=1, max_length=64),
    title: str = Form(..., min_length=1, max_length=255),
    album: str = Form(..., min_length=1, max_length=255),
    artist: str = Form(..., min_length=1, max_length=255),
    lyrics: str | None = Form(default=None, max_length=20_000),
    genre: str | None = Form(default=None, max_length=100),
    visibility: str = Form(default="public"),
    file: UploadFile = File(...),
    cover: UploadFile | None = File(default=None),
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
):
    """Bulk-upload entry point: one file per request, tagged with a
    caller-generated batch_id shared across the whole "Upload All" batch.
    Returns as soon as the file is queued -- never waits for storage,
    validation, analysis, or row creation, so a batch of many large files
    doesn't tie up a request per file. Reject-individually-not-the-batch: a
    bad file 422s its own request without touching any other file already
    queued under the same batch_id.
    """

    cover_storage_name = await _validate_and_store_cover(cover)
    fields = _clean_metadata_fields(
        album=album, artist=artist, title=title, lyrics=lyrics, genre=genre,
        visibility=visibility, cover_storage_name=cover_storage_name,
    )

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type.")
    max_bytes = uq.CATALOG_AUDIO_MAX_BYTES[content_type]
    data = await _read_limited(file, max_bytes)
    try:
        uq.validate_upload(file.filename or "track", content_type, data, max_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    position = uq.upload_queue.batch_size_so_far(batch_id)
    priority = _priority_for_batch_position(position)
    try:
        job = uq.upload_queue.submit(
            current_user.id,
            file.filename or "track",
            content_type,
            data,
            priority=priority,
            storage_subdir=CATALOG_AUDIO_SUBDIR,
            batch_id=batch_id,
            metadata=fields,
            max_size_override=max_bytes,
            on_stored_callback=_ON_STORED_CALLBACK,
            deep_audio_validation=True,
        )
    except Full:
        raise HTTPException(status_code=503, detail="Upload queue is full. Try again later.") from None

    return _job_to_read(job)


def _owned_job_or_404(job_id: str, current_user: User) -> dict:
    job = uq.upload_queue.public(job_id)
    if job is None or job["owner_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Upload job not found.")
    return job


@router.get("/tracks/batch-jobs/{job_id}", response_model=CatalogUploadJobRead)
def catalog_job_status(job_id: str, current_user: User = Depends(get_current_user)):
    job = _owned_job_or_404(job_id, current_user)
    return _job_to_read(job)


@router.post("/tracks/batch-jobs/{job_id}/retry", response_model=CatalogUploadJobRead)
def retry_catalog_job(job_id: str, current_user: User = Depends(get_current_user)):
    job = uq.upload_queue.retry_job(job_id, current_user.id)
    if job is None:
        raise HTTPException(
            status_code=409, detail="Only a failed job with its data still available can be retried."
        )
    return _job_to_read(job)


@router.post("/tracks/batch-jobs/{job_id}/cancel", response_model=CatalogUploadJobRead)
def cancel_catalog_job(job_id: str, current_user: User = Depends(get_current_user)):
    job = _owned_job_or_404(job_id, current_user)
    if not uq.upload_queue.cancel_job(job_id, current_user.id):
        raise HTTPException(status_code=409, detail="Only a still-queued job can be cancelled.")
    return _job_to_read(uq.upload_queue.public(job_id))


@router.get("/tracks/batches/{batch_id}", response_model=CatalogBatchStatusRead)
def catalog_batch_status(batch_id: str, current_user: User = Depends(get_current_user)):
    owned_jobs = [
        job for job in uq.upload_queue.jobs_for_batch(batch_id) if job["owner_id"] == current_user.id
    ]
    if not owned_jobs:
        raise HTTPException(status_code=404, detail="Batch not found.")
    results = [_job_to_read(job) for job in owned_jobs]
    counts = {"queued": 0, "validating": 0, "storing": 0, "analyzing": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for item in results:
        counts[item.status] += 1
    return CatalogBatchStatusRead(batch_id=batch_id, total=len(results), jobs=results, **counts)


@router.get("/tracks/{track_id}/audio")
def serve_catalog_track_audio(
    track_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog track not found.")
    # Same rule CandidateRetriever enforces at selection time (§12.2):
    # public, or owned by whoever's asking -- never anyone else's private
    # upload. A visitor who isn't authorized to hear it gets exactly the
    # same 404 as a track that doesn't exist, not a 403 that would confirm
    # a private track's existence.
    if row.visibility != "public" and row.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Catalog track not found.")
    root = (uq.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR).resolve()
    path = (root / row.storage_name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Catalog track audio is missing.")
    return FileResponse(
        path,
        media_type=row.content_type,
        filename=f"{row.artist} - {row.title}",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/tracks/{track_id}/cover")
def serve_catalog_track_cover(
    track_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if row is None or not row.cover_storage_name:
        raise HTTPException(status_code=404, detail="Cover art not found.")
    if row.visibility != "public" and row.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cover art not found.")
    root = (uq.UPLOAD_DIR / _COVER_SUBDIR).resolve()
    path = (root / row.cover_storage_name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Cover art file is missing.")
    media_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    }.get(path.suffix, "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
