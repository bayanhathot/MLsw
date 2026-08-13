"""Additive real-catalog upload: album/artist/lyrics are required alongside
the audio file, validated server-side by the same byte-signature check
attachments use, and a successful upload queues the same one-time
BPM/key/best-segment analysis job upload_queue.py already runs for step 5.

This is separate from POST /uploads/jobs (forum/message attachments): those
don't carry track metadata and aren't part of the AI-DJ catalog.
"""

import logging
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
from app.schemas import CatalogTrackRead
from app.services import upload_queue as uq
from app.services.pipeline.catalog_retriever import CATALOG_AUDIO_SUBDIR

router = APIRouter(prefix="/catalog", tags=["catalog"])
logger = logging.getLogger(__name__)

_AUDIO_CONTENT_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/flac"}
_MAX_AUDIO_BYTES = 10 * 1024 * 1024
_STORE_WAIT_SECONDS = 5.0


async def _read_limited(file: UploadFile, maximum_bytes: int) -> bytes:
    body = bytearray()
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > maximum_bytes:
            raise HTTPException(status_code=413, detail="File is too large.")
    return bytes(body)


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


def _to_read(row: CatalogTrack) -> CatalogTrackRead:
    return CatalogTrackRead(
        id=row.id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        genre=row.genre,
        duration_seconds=row.duration_seconds,
        analysis_status=row.analysis_status,
        audio_url=public_api_url(f"/catalog/tracks/{row.id}/audio"),
        created_at=row.created_at,
    )


@router.post("/tracks", response_model=CatalogTrackRead, status_code=status.HTTP_201_CREATED)
async def upload_catalog_track(
    album: str = Form(..., min_length=1, max_length=255),
    artist: str = Form(..., min_length=1, max_length=255),
    lyrics: str = Form(..., min_length=1, max_length=20_000),
    title: str | None = Form(default=None, max_length=255),
    genre: str | None = Form(default=None, max_length=100),
    file: UploadFile = File(...),
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    album, artist, lyrics = album.strip(), artist.strip(), lyrics.strip()
    if not album or not artist or not lyrics:
        raise HTTPException(status_code=422, detail="album, artist, and lyrics are required.")

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type.")
    data = await _read_limited(file, _MAX_AUDIO_BYTES)
    try:
        uq.validate_upload(file.filename or "track", content_type, data)
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
        )
    except Full:
        raise HTTPException(status_code=503, detail="Upload queue is full. Try again later.") from None

    job = _wait_for_store(job["job_id"])
    if job["status"] == "failed":
        raise HTTPException(status_code=422, detail=job["error"] or "Upload failed validation.")

    result = job["result"]
    storage_path = uq.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / result["storage_name"]
    duration_seconds = _probe_duration_seconds(storage_path)

    default_title = Path(file.filename or "Untitled").stem.strip() or "Untitled"
    row = CatalogTrack(
        owner_id=current_user.id,
        title=(title.strip() if title and title.strip() else default_title)[:255],
        artist=artist,
        album=album,
        lyrics=lyrics,
        genre=genre.strip() if genre and genre.strip() else None,
        storage_name=result["storage_name"],
        content_type=content_type,
        duration_seconds=duration_seconds,
        analysis_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    try:
        uq.upload_queue.submit_analysis(row.id)
    except Full:
        logger.warning("Analysis queue is full; catalog track %s stays pending.", row.id)

    return _to_read(row)


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
