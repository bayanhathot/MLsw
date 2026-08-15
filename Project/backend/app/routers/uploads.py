"""Bounded raw/batch uploads processed by a parallel priority queue."""

import base64
import binascii
import logging
from queue import Full
import unicodedata
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.rate_limit import write_rate_limit
from app.core.config import public_api_url
from app.database.database import get_db
from app.database.models.attachment import Attachment
from app.database.models.forum import ForumComment, ForumPost
from app.database.models.messaging import DirectMessage
from app.database.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas import AttachmentRead, UploadBatchRequest, UploadJobRead
from app.services import forum_service, social_service
from app.services.upload_queue import (
    ALLOWED_TYPES,
    UPLOAD_DIR,
    read_limited_stream,
    upload_queue,
    validate_upload,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)


def _decode_filename(value: str) -> str:
    """Decode the frontend's percent-encoded, header-safe Unicode filename."""

    hexadecimal = set("0123456789abcdefABCDEF")
    for index, character in enumerate(value):
        if character == "%" and (
            index + 2 >= len(value)
            or value[index + 1] not in hexadecimal
            or value[index + 2] not in hexadecimal
        ):
            raise HTTPException(status_code=422, detail="Filename encoding is invalid.")
    try:
        decoded = unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="Filename encoding is invalid.") from None
    decoded = unicodedata.normalize("NFC", decoded)
    if not decoded or len(decoded) > 255 or any(
        ord(character) < 32 or ord(character) == 127 for character in decoded
    ):
        raise HTTPException(status_code=422, detail="Filename is invalid.")
    return decoded


async def _read_limited_body(request: Request, maximum_bytes: int) -> bytes:
    return await read_limited_stream(request.stream(), maximum_bytes)


def _public_job(db: Session, job: dict, current_user: User) -> UploadJobRead:
    if job["owner_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Upload job not found.")
    attachment = None
    if job["status"] == "completed":
        with upload_queue.materialization_lock(job["job_id"]):
            current = upload_queue.public(job["job_id"]) or job
            if current["attachment_id"] is not None:
                attachment = db.query(Attachment).filter_by(id=current["attachment_id"]).first()
            else:
                result = current["result"]
                attachment = Attachment(
                    owner_id=current_user.id,
                    kind=result["kind"],
                    filename=current["filename"],
                    content_type=current["content_type"],
                    storage_name=result["storage_name"],
                    url="pending",
                    size_bytes=result["size_bytes"],
                    sha256=result["sha256"],
                )
                try:
                    db.add(attachment)
                    db.flush()
                    attachment.url = public_api_url(f"/uploads/{attachment.id}")
                    db.commit()
                    db.refresh(attachment)
                except IntegrityError:
                    # A separate process may have won the unique storage-name
                    # race even though in-process callers share the lock.
                    db.rollback()
                    attachment = db.query(Attachment).filter_by(
                        storage_name=result["storage_name"]
                    ).first()
                    if attachment is None:
                        raise HTTPException(
                            status_code=503,
                            detail="Upload completed but metadata is not available yet.",
                        ) from None
                upload_queue.set_attachment(job["job_id"], attachment.id)
    return UploadJobRead(
        job_id=job["job_id"],
        status=job["status"],
        priority=job["priority"],
        attachment=AttachmentRead.model_validate(attachment) if attachment else None,
        error=job["error"],
    )


@router.post("/jobs", response_model=UploadJobRead, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_upload(
    request: Request,
    priority: int = Query(default=5, ge=0, le=10),
    encoded_filename: str = Header(alias="X-Filename", min_length=1, max_length=1024),
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = _decode_filename(encoded_filename)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    config = ALLOWED_TYPES.get(content_type)
    if config is None:
        raise HTTPException(status_code=415, detail="Unsupported media type.")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from None
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
        if declared_length > config[2]:
            raise HTTPException(status_code=413, detail="File is too large.")
    data = await _read_limited_body(request, config[2])
    try:
        job = upload_queue.submit(current_user.id, filename, content_type, data, priority)
    except Full:
        raise HTTPException(status_code=503, detail="Upload queue is full. Try again later.") from None
    return _public_job(db, job, current_user)


@router.post("/batch", response_model=list[UploadJobRead], status_code=status.HTTP_202_ACCEPTED)
def enqueue_batch(
    request: UploadBatchRequest,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = []
    total = 0
    for item in request.files:
        try:
            data = base64.b64decode(item.data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail=f"Invalid base64 for {item.filename}.") from None
        total += len(data)
        # Base64 adds roughly 33%; keeping decoded content to 7 MiB keeps the
        # complete JSON request under the reverse proxy's 10 MiB limit.
        if total > 7 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Batch exceeds the 7 MiB decoded limit.")
        try:
            validate_upload(item.filename, item.content_type, data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{item.filename}: {exc}") from None
        items.append((current_user.id, item.filename, item.content_type, data, item.priority))
    try:
        jobs = upload_queue.submit_many(items)
    except Full:
        raise HTTPException(status_code=503, detail="Upload queue is full. Try again later.") from None
    return [_public_job(db, job, current_user) for job in jobs]


@router.get("/jobs/{job_id}", response_model=UploadJobRead)
def upload_status(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = upload_queue.public(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload job not found.")
    return _public_job(db, job, current_user)


@router.get("/{attachment_id}")
def serve_attachment(
    attachment_id: int,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    attachment = db.query(Attachment).filter_by(id=attachment_id).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    viewer_id = current_user.id if current_user else None
    permitted = current_user is not None and attachment.owner_id == current_user.id
    publicly_cacheable = False

    if not permitted and attachment.post_id is not None:
        post = db.query(ForumPost).filter_by(id=attachment.post_id).first()
        if post is not None and forum_service.can_view_post(db, post, viewer_id):
            permitted = True
            publicly_cacheable = post.visibility == "public"
    elif not permitted and attachment.comment_id is not None:
        comment = db.query(ForumComment).filter_by(id=attachment.comment_id).first()
        if comment is not None:
            post = db.query(ForumPost).filter_by(id=comment.post_id).first()
            author_blocked = viewer_id is not None and social_service.is_blocked_between(
                db, viewer_id, comment.author_id
            )
            if post is not None and forum_service.can_view_post(db, post, viewer_id) and not author_blocked:
                permitted = True
                publicly_cacheable = post.visibility == "public"
    elif not permitted and attachment.message_id is not None and current_user is not None:
        message = db.query(DirectMessage).filter_by(id=attachment.message_id).first()
        permitted = bool(message and current_user.id in {message.sender_id, message.recipient_id})

    if not permitted:
        raise HTTPException(status_code=403, detail="You cannot access this attachment.")
    path = (UPLOAD_DIR / attachment.storage_name).resolve()
    if path.parent != UPLOAD_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file is missing.")
    cache_control = "public, max-age=3600" if publicly_cacheable else "private, no-store"
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": cache_control, "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unused_attachment(
    attachment_id: int,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachment = db.query(Attachment).filter_by(id=attachment_id).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    if attachment.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this attachment.")
    if any((attachment.post_id, attachment.comment_id, attachment.message_id)):
        raise HTTPException(status_code=409, detail="Attached media must be removed with its post, comment, or message.")
    path = (UPLOAD_DIR / attachment.storage_name).resolve()
    db.delete(attachment)
    db.commit()
    if path.parent == UPLOAD_DIR.resolve():
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Attachment row deleted but bytes could not be removed: %s", exc)
