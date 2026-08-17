"""Additive real-catalog upload: album/artist are required alongside the
audio file (lyrics stay optional -- instrumental tracks are first-class, see
ai-dj-segment-metadata-architecture.md §3), validated server-side by the
same byte-signature check attachments use, and a successful upload queues
the same one-time BPM/key/best-segment analysis job upload_queue.py already
runs for step 5.

Two upload shapes share the same underlying UploadQueue (never a second job
system, per the architecture doc's ingest rules):

- POST /catalog/tracks: the original single-file path. Synchronous from the
  caller's perspective -- it waits (briefly) for the file to finish storing,
  then returns the created row directly.
- POST /catalog/tracks/batch-jobs (+ polling): the bulk-upload path. Returns
  immediately with a job_id; the CatalogTrack row is created lazily, the
  first time a completed job is polled (same lazy-materialization pattern
  routers/uploads.py already uses for attachments) -- never inline at
  request/enqueue time. Every file in one "Upload All" batch shares a
  client-generated batch_id, which also drives fair-share priority so one
  huge batch can't starve a smaller one queued alongside it.

This is separate from POST /uploads/jobs (forum/message attachments): those
don't carry track metadata and aren't part of the AI-DJ catalog.
"""

import logging
import os
from pathlib import Path
from queue import Full
from time import monotonic, sleep

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.catalog import CatalogTrack
from app.database.models.user import User
from app.routers.auth import get_current_user
from app.schemas import CatalogBatchStatusRead, CatalogTrackRead, CatalogUploadJobRead
from app.services import upload_queue as uq
from app.services.pipeline.catalog_retriever import CATALOG_AUDIO_SUBDIR

router = APIRouter(prefix="/catalog", tags=["catalog"])
logger = logging.getLogger(__name__)

_AUDIO_CONTENT_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/flac"}
_VISIBILITIES = {"private", "public"}
_STORE_WAIT_SECONDS = 5.0
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
    deadline = monotonic() + _STORE_WAIT_SECONDS
    job = uq.upload_queue.public(job_id)
    while job is not None and job["status"] in {"queued", "processing"} and monotonic() < deadline:
        sleep(0.01)
        job = uq.upload_queue.public(job_id)
    if job is None or job["status"] not in {"completed", "failed"}:
        raise HTTPException(
            status_code=503, detail="Upload is taking longer than expected. Try again."
        )
    return job


def _clean_metadata_fields(
    *, album: str, artist: str, lyrics: str | None, title: str | None, genre: str | None, visibility: str
) -> dict:
    album, artist = album.strip(), artist.strip()
    if not album or not artist:
        raise HTTPException(status_code=422, detail="album and artist are required.")
    if visibility not in _VISIBILITIES:
        raise HTTPException(status_code=422, detail="visibility must be 'private' or 'public'.")
    return {
        "album": album,
        "artist": artist,
        "lyrics": lyrics.strip() if lyrics and lyrics.strip() else None,
        "title": title.strip() if title and title.strip() else None,
        "genre": genre.strip() if genre and genre.strip() else None,
        "visibility": visibility,
    }


def _build_catalog_track(
    *,
    owner_id: int,
    filename: str,
    content_type: str,
    storage_name: str,
    sha256: str,
    duration_seconds: int,
    fields: dict,
) -> CatalogTrack:
    default_title = Path(filename or "Untitled").stem.strip() or "Untitled"
    return CatalogTrack(
        owner_id=owner_id,
        title=(fields["title"] or default_title)[:255],
        artist=fields["artist"],
        album=fields["album"],
        lyrics=fields["lyrics"],
        genre=fields["genre"],
        visibility=fields["visibility"],
        storage_name=storage_name,
        content_type=content_type,
        duration_seconds=duration_seconds,
        analysis_status="pending",
        checksum_sha256=sha256,
    )


def _dispatch_analysis(track_id: int) -> None:
    try:
        uq.upload_queue.submit_analysis(track_id)
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
        created_at=row.created_at,
    )


@router.post("/tracks", response_model=CatalogTrackRead, status_code=status.HTTP_201_CREATED)
async def upload_catalog_track(
    album: str = Form(..., min_length=1, max_length=255),
    artist: str = Form(..., min_length=1, max_length=255),
    lyrics: str | None = Form(default=None, max_length=20_000),
    title: str | None = Form(default=None, max_length=255),
    genre: str | None = Form(default=None, max_length=100),
    visibility: str = Form(default="private"),
    file: UploadFile = File(...),
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fields = _clean_metadata_fields(
        album=album, artist=artist, lyrics=lyrics, title=title, genre=genre, visibility=visibility
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
        filename=file.filename or "track",
        content_type=content_type,
        storage_name=result["storage_name"],
        sha256=result["sha256"],
        duration_seconds=duration_seconds,
        fields=fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    _dispatch_analysis(row.id)

    return _to_read(row)


@router.post(
    "/tracks/batch-jobs", response_model=CatalogUploadJobRead, status_code=status.HTTP_202_ACCEPTED
)
async def enqueue_catalog_track(
    batch_id: str = Form(..., min_length=1, max_length=64),
    album: str = Form(..., min_length=1, max_length=255),
    artist: str = Form(..., min_length=1, max_length=255),
    lyrics: str | None = Form(default=None, max_length=20_000),
    title: str | None = Form(default=None, max_length=255),
    genre: str | None = Form(default=None, max_length=100),
    visibility: str = Form(default="private"),
    file: UploadFile = File(...),
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
):
    """Bulk-upload entry point: one file per request, tagged with a
    caller-generated batch_id shared across the whole "Upload All" batch.
    Returns as soon as the file is queued -- never waits for storage,
    analysis, or row creation, so a batch of many large files doesn't tie up
    a request per file. Reject-individually-not-the-batch: a bad file 422s
    its own request without touching any other file already queued under
    the same batch_id.
    """

    fields = _clean_metadata_fields(
        album=album, artist=artist, lyrics=lyrics, title=title, genre=genre, visibility=visibility
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
        )
    except Full:
        raise HTTPException(status_code=503, detail="Upload queue is full. Try again later.") from None

    return CatalogUploadJobRead(
        job_id=job["job_id"],
        batch_id=batch_id,
        filename=job["filename"],
        status=job["status"],
        priority=job["priority"],
        track=None,
        error=None,
    )


def _materialize_catalog_job(db: Session, job: dict, current_user: User) -> CatalogUploadJobRead:
    if job["owner_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Upload job not found.")
    track = None
    if job["status"] == "completed":
        with uq.upload_queue.materialization_lock(job["job_id"]):
            current = uq.upload_queue.public(job["job_id"]) or job
            if current["catalog_track_id"] is not None:
                track = db.query(CatalogTrack).filter_by(id=current["catalog_track_id"]).first()
            else:
                result = current["result"]
                fields = current["metadata"] or {}
                storage_path = uq.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / result["storage_name"]
                duration_seconds = _probe_duration_seconds(storage_path)
                row = _build_catalog_track(
                    owner_id=current_user.id,
                    filename=current["filename"],
                    content_type=current["content_type"],
                    storage_name=result["storage_name"],
                    sha256=result["sha256"],
                    duration_seconds=duration_seconds,
                    fields=fields,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                uq.upload_queue.set_catalog_track(job["job_id"], row.id)
                _dispatch_analysis(row.id)
                track = row
    return CatalogUploadJobRead(
        job_id=job["job_id"],
        batch_id=job["batch_id"] or "",
        filename=job["filename"],
        status=job["status"],
        priority=job["priority"],
        track=_to_read(track) if track is not None else None,
        error=job["error"],
    )


@router.get("/tracks/batch-jobs/{job_id}", response_model=CatalogUploadJobRead)
def catalog_job_status(
    job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = uq.upload_queue.public(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload job not found.")
    return _materialize_catalog_job(db, job, current_user)


@router.get("/tracks/batches/{batch_id}", response_model=CatalogBatchStatusRead)
def catalog_batch_status(
    batch_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    owned_jobs = [
        job for job in uq.upload_queue.jobs_for_batch(batch_id) if job["owner_id"] == current_user.id
    ]
    if not owned_jobs:
        raise HTTPException(status_code=404, detail="Batch not found.")
    results = [_materialize_catalog_job(db, job, current_user) for job in owned_jobs]
    counts = {"queued": 0, "processing": 0, "completed": 0, "failed": 0}
    for item in results:
        counts[item.status] += 1
    return CatalogBatchStatusRead(batch_id=batch_id, total=len(results), jobs=results, **counts)


@router.get("/tracks/{track_id}/audio")
def serve_catalog_track_audio(track_id: int, db: Session = Depends(get_db)):
    row = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if row is None:
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
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
