"""Parallel priority queue for bounded media validation and storage."""

import hashlib
import logging
import os
from collections.abc import AsyncIterable
from itertools import count
from pathlib import Path
from queue import Full, PriorityQueue
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def read_limited_stream(chunks: AsyncIterable[bytes], maximum_bytes: int) -> bytes:
    """Read an async byte-chunk stream without ever buffering past the limit.

    Shared by every upload path (catalog tracks, forum/message/DM
    attachments) that needs a hard body-size cap enforced while streaming,
    rather than after a full read.
    """

    body = bytearray()
    async for chunk in chunks:
        if len(body) + len(chunk) > maximum_bytes:
            raise HTTPException(status_code=413, detail="File is too large.")
        body.extend(chunk)
    return bytes(body)


# Sentinel job_id prefix for analysis-only tasks pushed onto the same
# worker pool (requirement 5: reuse this queue, don't build a second async
# system). These never occupy self._jobs -- there's nothing for a client to
# poll, the caller already has the catalog_track_id it queued.
_ANALYZE_PREFIX = "analyze:"

ALLOWED_TYPES = {
    "image/jpeg": ("image", ".jpg", 8 * 1024 * 1024),
    "image/png": ("image", ".png", 8 * 1024 * 1024),
    "image/webp": ("image", ".webp", 8 * 1024 * 1024),
    "image/gif": ("image", ".gif", 8 * 1024 * 1024),
    # Kept at 10 MiB to match the reverse-proxy request body limit.
    "video/mp4": ("video", ".mp4", 10 * 1024 * 1024),
    "video/webm": ("video", ".webm", 10 * 1024 * 1024),
    "audio/mpeg": ("audio", ".mp3", 10 * 1024 * 1024),
    "audio/wav": ("audio", ".wav", 10 * 1024 * 1024),
    "audio/ogg": ("audio", ".ogg", 10 * 1024 * 1024),
    "audio/flac": ("audio", ".flac", 10 * 1024 * 1024),
}
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", Path(__file__).resolve().parents[1] / "uploads"))


def _matches_signature(content_type: str, data: bytes) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if content_type == "video/mp4":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if content_type == "video/webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if content_type == "audio/mpeg":
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if content_type == "audio/wav":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if content_type == "audio/ogg":
        return data.startswith(b"OggS")
    if content_type == "audio/flac":
        return data.startswith(b"fLaC")
    return False


def validate_upload(filename: str, content_type: str, data: bytes) -> tuple[str, str, int]:
    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported media type.")
    kind, extension, max_size = ALLOWED_TYPES[content_type]
    if not data:
        raise ValueError("File is empty.")
    if len(data) > max_size:
        raise ValueError(f"File exceeds the {max_size // (1024 * 1024)} MiB limit.")
    if not _matches_signature(content_type, data):
        raise ValueError("File signature does not match its declared media type.")
    if not Path(filename).name or filename in {".", ".."}:
        raise ValueError("Invalid filename.")
    return kind, extension, max_size


class UploadQueue:
    """In-memory queue; completed files are durable, job metadata is not."""

    def __init__(self, workers: int = 4, capacity: int = 32, max_history: int = 1000) -> None:
        self._queue: PriorityQueue = PriorityQueue(maxsize=capacity)
        self._jobs: dict[str, dict] = {}
        self._materialization_locks: dict[str, Lock] = {}
        self._lock = Lock()
        self._submission_lock = Lock()
        self._sequence = count()
        self._max_history = max_history
        self._unclaimed_ttl = max(60, int(os.getenv("UPLOAD_JOB_TTL_SECONDS", "3600")))
        self._cleanup_wakeup = Event()
        for index in range(workers):
            Thread(target=self._worker, name=f"zonix-upload-{index}", daemon=True).start()
        if workers > 0:
            Thread(target=self._cleanup_worker, name="zonix-upload-cleanup", daemon=True).start()

    def _new_job(
        self,
        owner_id: int,
        filename: str,
        content_type: str,
        priority: int,
        storage_subdir: str = "",
    ) -> dict:
        job_id = f"upload_{uuid4().hex}"
        return {
            "job_id": job_id,
            "owner_id": owner_id,
            "filename": filename.replace("\\", "/").rsplit("/", 1)[-1],
            "content_type": content_type.split(";", 1)[0].strip().lower(),
            "priority": priority,
            # "" stores at UPLOAD_DIR root (attachments); a subdirectory name
            # (e.g. "catalog") keeps other upload kinds in their own namespace.
            "storage_subdir": storage_subdir,
            "status": "queued",
            "error": None,
            "result": None,
            "attachment_id": None,
            "created_at_monotonic": monotonic(),
            "completed_at_monotonic": None,
        }

    def _prune(self) -> None:
        expired_files: list[str] = []
        with self._lock:
            now = monotonic()
            expired_unclaimed = [
                key
                for key, job in self._jobs.items()
                if job["status"] == "completed"
                and job["attachment_id"] is None
                and job["completed_at_monotonic"] is not None
                and now - job["completed_at_monotonic"] >= self._unclaimed_ttl
            ]
            removable = list(expired_unclaimed)
            remaining_count = len(self._jobs) - len(expired_unclaimed)
            history_slots_needed = max(0, remaining_count - self._max_history + 1)
            if history_slots_needed:
                removable.extend(
                    key
                    for key, job in self._jobs.items()
                    if key not in expired_unclaimed
                    and (
                        job["status"] == "failed"
                        or (job["status"] == "completed" and job["attachment_id"] is not None)
                    )
                )
            for key in removable[: len(expired_unclaimed) + history_slots_needed]:
                job = self._jobs.pop(key, None)
                self._materialization_locks.pop(key, None)
                if job and job["status"] == "completed" and job["attachment_id"] is None:
                    expired_files.append(job["result"]["storage_name"])
        for storage_name in expired_files:
            try:
                (UPLOAD_DIR / storage_name).unlink(missing_ok=True)
            except OSError:
                # Capacity remains bounded even if an operator must later
                # remove an unreadable file manually.
                pass

    def _cleanup_worker(self) -> None:
        """Expire unclaimed files even when no later submission arrives."""

        interval = max(60, min(300, self._unclaimed_ttl // 2))
        while not self._cleanup_wakeup.wait(interval):
            self._prune()

    def submit(
        self,
        owner_id: int,
        filename: str,
        content_type: str,
        data: bytes,
        priority: int,
        storage_subdir: str = "",
    ) -> dict:
        with self._submission_lock:
            self._prune()
            with self._lock:
                if len(self._jobs) >= self._max_history:
                    raise Full
            if self._queue.full():
                raise Full
            job = self._new_job(owner_id, filename, content_type, priority, storage_subdir)
            job_id = job["job_id"]
            with self._lock:
                self._jobs[job_id] = job
            self._queue.put_nowait((-priority, next(self._sequence), job_id, data))
        return self.public(job_id)

    def submit_analysis(self, catalog_track_id: int, priority: int = 5) -> None:
        """Queue a post-store analysis task on the same worker pool.

        Fire-and-forget: there is no job status to poll here, the caller
        already holds the catalog_track_id it queued and can read the
        CatalogTrack row's analysis_status directly once it wants to know.
        """

        self._queue.put_nowait(
            (-priority, next(self._sequence), f"{_ANALYZE_PREFIX}{catalog_track_id}", None)
        )

    def submit_many(self, items: list[tuple[int, str, str, bytes, int]]) -> list[dict]:
        """Atomically accept a batch or enqueue none of it."""

        with self._submission_lock:
            self._prune()
            with self._lock:
                if len(self._jobs) + len(items) > self._max_history:
                    raise Full
            if self._queue.maxsize and self._queue.qsize() + len(items) > self._queue.maxsize:
                raise Full
            jobs = [self._new_job(owner_id, filename, content_type, priority) for owner_id, filename, content_type, _, priority in items]
            with self._lock:
                self._jobs.update({job["job_id"]: job for job in jobs})
            try:
                for job, (_, _, _, data, priority) in zip(jobs, items):
                    self._queue.put_nowait((-priority, next(self._sequence), job["job_id"], data))
            except Full:
                # This is only defensive: other producers are serialized and
                # consumers can only free capacity after the check.
                with self._lock:
                    for job in jobs:
                        self._jobs.pop(job["job_id"], None)
                raise
        return [self.public(job["job_id"]) for job in jobs]

    def public(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def set_attachment(self, job_id: str, attachment_id: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["attachment_id"] = attachment_id

    def materialization_lock(self, job_id: str) -> Lock:
        """Serialize Attachment row creation for concurrent status polls."""

        with self._lock:
            return self._materialization_locks.setdefault(job_id, Lock())

    def _worker(self) -> None:
        while True:
            _, _, job_id, data = self._queue.get()
            if job_id.startswith(_ANALYZE_PREFIX):
                self._run_analysis(job_id[len(_ANALYZE_PREFIX):])
                self._queue.task_done()
                continue
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "processing"
            try:
                kind, extension, _ = validate_upload(job["filename"], job["content_type"], data)
                storage_name = f"{uuid4().hex}{extension}"
                target_dir = UPLOAD_DIR / job["storage_subdir"] if job["storage_subdir"] else UPLOAD_DIR
                target_dir.mkdir(parents=True, exist_ok=True)
                path = target_dir / storage_name
                path.write_bytes(data)
                result = {
                    "kind": kind,
                    "storage_name": storage_name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                with self._lock:
                    job["result"] = result
                    job["status"] = "completed"
                    job["completed_at_monotonic"] = monotonic()
            except (OSError, ValueError) as exc:
                with self._lock:
                    job["status"] = "failed"
                    job["error"] = str(exc)
            finally:
                self._queue.task_done()

    @staticmethod
    def _run_analysis(catalog_track_id_text: str) -> None:
        try:
            catalog_track_id = int(catalog_track_id_text)
            # Imported lazily so importing this module never pulls in
            # librosa's heavy dependency tree unless an analysis task
            # actually runs.
            from app.services.audio_analysis import analyze_catalog_track

            analyze_catalog_track(catalog_track_id)
        except Exception:
            logger.exception("Catalog track analysis job failed for id=%s", catalog_track_id_text)


upload_queue = UploadQueue(
    workers=max(1, min(8, int(os.getenv("UPLOAD_WORKERS", "4")))),
    capacity=max(1, min(256, int(os.getenv("UPLOAD_QUEUE_CAPACITY", "32")))),
)
