"""Parallel priority queue for bounded media validation and storage.

Durability (Job Queue milestone hardening): the raw bytes of every upload
are written to a durable "pending" location on disk *before* the job is
considered queued, and each job's record (status/priority/batch_id/
metadata/result/error/timestamps) is mirrored into Redis (REDIS_URL) on
every state change. Together, that means a job that's still queued or
mid-flight survives a process crash/restart: UploadQueue.__init__ re-hydrates
every job from Redis, and any job that was still active gets re-enqueued,
reading its bytes back from the pending file rather than from memory (which
the crash/restart lost).

Fails open when Redis is unconfigured/unreachable: falls back to the
original in-memory-only behavior (job state lost on restart), the same
posture the rest of this codebase already applies to Redis (see
redis_client.py/channel_hub.py) -- durability is additive, not a hard
dependency for uploads to work at all.

Domain-agnostic by design: this module knows nothing about CatalogTrack or
Attachment rows. A caller that needs a DB row created once a job's bytes are
safely stored registers a named callback (register_callback) and passes its
name to submit(); the worker invokes it by name, not by direct reference, so
a job recovered after a restart can still find the right handler once the
owning module re-registers the same name at import time (a Python callable
itself can't survive a restart, but its name always resolves the same way).
"""

import hashlib
import io
import json
import logging
import os
from collections.abc import AsyncIterable, Callable
from itertools import count
from pathlib import Path
from queue import Full, PriorityQueue
from threading import Event, Lock, Thread
from time import monotonic, time
from uuid import uuid4

from fastapi import HTTPException

from app.core.redis_client import get_sync_redis_client

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
# poll directly; an associated upload job_id (see submit_analysis) is what
# lets _run_analysis mark that job "completed" once analysis finishes.
_ANALYZE_PREFIX = "analyze:"
# Same idea, for external_tracks (Prompt 3's persistent Audius analysis
# cache) -- a first-time Audius encounter has no upload job of its own to
# associate with (nothing was ever uploaded), so this prefix carries just
# the external_track_id, nothing else. Shares this same bounded worker
# pool/queue rather than a second one specifically so external-track
# analysis dispatch is automatically capped at this process's existing
# `workers` concurrency -- Audius documents no explicit rate limit this
# codebase is aware of, so that shared bound is the only concurrency cap
# in effect (see pipeline/external_track_cache.py's own module docstring).
_ANALYZE_EXTERNAL_PREFIX = "analyze_external:"

# Compressed formats (mp3/ogg) vs. lossless (wav/flac) genuinely need
# different ceilings for the same clip length -- a 3-minute uncompressed WAV
# is already ~31 MB (44,100 samples/sec x 16 bits x 2 channels / 8 x 180
# sec), so one flat cap across all four audio types either rejects a
# perfectly ordinary WAV/FLAC clip or is needlessly loose for MP3/OGG. This
# is the generic-attachment (forum/message clip) tier, used by ALLOWED_TYPES
# below; routers/catalog.py's full-length track uploads are a different use
# case with their own, separately-configured ceiling -- see
# CATALOG_AUDIO_MAX_BYTES further down, which overrides these via
# validate_upload's max_size_override and is untouched by this pair. Both
# env-configurable, matching UPLOAD_WORKERS/UPLOAD_QUEUE_CAPACITY's own style.
_ATTACHMENT_AUDIO_MAX_MB_COMPRESSED = max(
    1, min(200, int(os.getenv("ATTACHMENT_AUDIO_MAX_MB_COMPRESSED", "10")))
)
_ATTACHMENT_AUDIO_MAX_MB_LOSSLESS = max(
    1, min(500, int(os.getenv("ATTACHMENT_AUDIO_MAX_MB_LOSSLESS", "100")))
)

ALLOWED_TYPES = {
    "image/jpeg": ("image", ".jpg", 8 * 1024 * 1024),
    "image/png": ("image", ".png", 8 * 1024 * 1024),
    "image/webp": ("image", ".webp", 8 * 1024 * 1024),
    "image/gif": ("image", ".gif", 8 * 1024 * 1024),
    # Kept at 10 MiB to match the reverse-proxy request body limit.
    "video/mp4": ("video", ".mp4", 10 * 1024 * 1024),
    "video/webm": ("video", ".webm", 10 * 1024 * 1024),
    "audio/mpeg": ("audio", ".mp3", _ATTACHMENT_AUDIO_MAX_MB_COMPRESSED * 1024 * 1024),
    "audio/ogg": ("audio", ".ogg", _ATTACHMENT_AUDIO_MAX_MB_COMPRESSED * 1024 * 1024),
    "audio/wav": ("audio", ".wav", _ATTACHMENT_AUDIO_MAX_MB_LOSSLESS * 1024 * 1024),
    "audio/flac": ("audio", ".flac", _ATTACHMENT_AUDIO_MAX_MB_LOSSLESS * 1024 * 1024),
}
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", Path(__file__).resolve().parents[1] / "uploads"))
# Where submit() durably parks raw bytes before a worker has even looked at
# them -- inside UPLOAD_DIR so it shares that volume's persistence, but its
# own subdirectory so pending files are never mistaken for finished ones.
_PENDING_SUBDIR = "_pending"

# routers/catalog.py's full-length track upload ceiling -- see this pair's
# generic-attachment counterpart above (_ATTACHMENT_AUDIO_MAX_MB_*) for why
# compressed and lossless formats need different tiers in the first place.
# A full song is a much larger, but much rarer, upload than a short
# forum/message clip, hence its own higher, separately-configured ceiling
# rather than sharing ALLOWED_TYPES' -- applied via validate_upload's
# max_size_override, never touching ALLOWED_TYPES itself.
_CATALOG_AUDIO_MAX_MB_COMPRESSED = max(
    1, min(500, int(os.getenv("CATALOG_AUDIO_MAX_MB_COMPRESSED", "30")))
)
_CATALOG_AUDIO_MAX_MB_LOSSLESS = max(
    1, min(500, int(os.getenv("CATALOG_AUDIO_MAX_MB_LOSSLESS", "100")))
)
CATALOG_AUDIO_MAX_BYTES = {
    "audio/mpeg": _CATALOG_AUDIO_MAX_MB_COMPRESSED * 1024 * 1024,
    "audio/ogg": _CATALOG_AUDIO_MAX_MB_COMPRESSED * 1024 * 1024,
    "audio/wav": _CATALOG_AUDIO_MAX_MB_LOSSLESS * 1024 * 1024,
    "audio/flac": _CATALOG_AUDIO_MAX_MB_LOSSLESS * 1024 * 1024,
}

# Every job status a job can ever be in. The first four are transient
# (a job in one of these was mid-flight if a restart is recovering it);
# the last three are terminal.
_ACTIVE_STATUSES = {"queued", "validating", "storing", "analyzing"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Named on_stored_callback hooks a domain module registers at import time --
# see register_callback()'s docstring for why this is name-based rather than
# a direct callable reference.
_CALLBACKS: dict[str, Callable[[str], None]] = {}
# Optional hook invoked once a job's associated analyze_catalog_track run
# finishes (success or failure) -- see submit_analysis's upload_job_id.
_ANALYSIS_COMPLETE_CALLBACKS: dict[str, Callable[[str, int], None]] = {}


def register_callback(name: str, fn: Callable[[str], None]) -> None:
    """Registers a named hook the worker invokes (by name, with just a
    job_id) right after a job's bytes finish storing -- e.g.
    routers/catalog.py registers one to create the CatalogTrack row and
    dispatch analysis. Re-registering the same name simply replaces it
    (idempotent for a module that registers once at import time, which is
    the only way this is ever called)."""

    _CALLBACKS[name] = fn


def register_analysis_complete_callback(name: str, fn: Callable[[str, int], None]) -> None:
    """Registers a named hook invoked with (upload_job_id, catalog_track_id)
    once that track's analyze_catalog_track run finishes, regardless of
    whether analysis itself succeeded -- upload success and analysis
    success are different questions (see routers/catalog.py)."""

    _ANALYSIS_COMPLETE_CALLBACKS[name] = fn


# Fires on *every* status transition (queued/validating/storing/analyzing/
# completed/failed/cancelled), unlike the two callbacks above, which each
# fire once at one specific point. Plain functions in a list, not a name
# registry -- unlike _CALLBACKS/_ANALYSIS_COMPLETE_CALLBACKS, nothing needs
# to look one of these back up by name after a restart (they're for live
# observability -- e.g. routers/catalog.py pushing a WebSocket update and
# firing a notification on a terminal state -- not for resuming work), so a
# plain re-append on import is fine. Called with the job's dict snapshot;
# exceptions are caught and logged, never allowed to break the worker.
_STATUS_LISTENERS: list[Callable[[dict], None]] = []


def add_status_listener(fn: Callable[[dict], None]) -> None:
    _STATUS_LISTENERS.append(fn)


def _notify_status_listeners(job: dict) -> None:
    for fn in _STATUS_LISTENERS:
        try:
            fn(job)
        except Exception:
            logger.exception("upload_queue status listener failed for job %s", job.get("job_id"))


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


def validate_upload(
    filename: str, content_type: str, data: bytes, max_size_override: int | None = None
) -> tuple[str, str, int]:
    """Cheap, synchronous checks only: signature + size + filename. Deep
    audio validation (actually decodable, not silent/too short) is a
    separate, more expensive step -- see _validate_decodable_audio, run only
    by the worker, never inline in a request."""

    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported media type.")
    kind, extension, max_size = ALLOWED_TYPES[content_type]
    if max_size_override is not None:
        max_size = max_size_override
    if not data:
        raise ValueError("File is empty.")
    if len(data) > max_size:
        format_name = extension.lstrip(".").upper()
        raise ValueError(f"File exceeds the {max_size // (1024 * 1024)} MiB cap for {format_name}.")
    if not _matches_signature(content_type, data):
        raise ValueError("File signature does not match its declared media type.")
    if not Path(filename).name or filename in {".", ".."}:
        raise ValueError("Invalid filename.")
    return kind, extension, max_size


def _validate_decodable_audio(data: bytes, extension: str) -> dict:
    """Actually decodes the audio (not just its byte signature), catching a
    truncated/corrupt file a valid-looking header can still pass, plus
    silence and unusably short clips. Raises ValueError with a plain,
    user-facing reason; a merely unusual-but-fine track (mono, low sample
    rate) never raises -- only something genuinely unplayable does."""

    from pydub import AudioSegment

    try:
        segment = AudioSegment.from_file(io.BytesIO(data), format=extension.lstrip("."))
    except Exception as exc:
        raise ValueError("Could not decode this file as playable audio.") from exc
    if len(segment) < 1000:
        raise ValueError("Audio is too short to be a usable track (minimum 1 second).")
    if segment.rms == 0:
        raise ValueError("Audio appears to be silent.")
    if segment.frame_rate <= 0 or segment.channels <= 0:
        raise ValueError("Audio has an invalid sample rate or channel count.")
    return {
        "duration_ms": len(segment),
        "channels": segment.channels,
        "frame_rate": segment.frame_rate,
    }


def _redis_job_key(job_id: str) -> str:
    return f"cuemix:upload:job:{job_id}"


def _redis_batch_key(batch_id: str) -> str:
    return f"cuemix:upload:batch:{batch_id}"


_REDIS_ALL_JOBS_KEY = "cuemix:upload:jobs"


class UploadQueue:
    """Bounded in-process priority dispatch (unchanged scheduling logic),
    backed by a durable Redis-mirrored job store when REDIS_URL is
    configured and reachable; falls back to in-memory-only otherwise."""

    def __init__(self, workers: int = 4, capacity: int = 32, max_history: int = 1000) -> None:
        self._queue: PriorityQueue = PriorityQueue(maxsize=capacity)
        self._jobs: dict[str, dict] = {}
        self._materialization_locks: dict[str, Lock] = {}
        # Caller-supplied batch_id -> the job_ids submitted under it (see
        # submit()'s batch_id param and jobs_for_batch() below). Membership
        # is pruned in lockstep with _jobs itself -- a batch view is just an
        # aggregation over still-tracked jobs, not a separately durable thing
        # beyond what Redis already mirrors.
        self._batches: dict[str, set[str]] = {}
        self._lock = Lock()
        self._submission_lock = Lock()
        self._sequence = count()
        self._max_history = max_history
        self._unclaimed_ttl = max(60, int(os.getenv("UPLOAD_JOB_TTL_SECONDS", "3600")))
        self._cleanup_wakeup = Event()
        (UPLOAD_DIR / _PENDING_SUBDIR).mkdir(parents=True, exist_ok=True)
        self._recover()
        for index in range(workers):
            Thread(target=self._worker, name=f"cuemix-upload-{index}", daemon=True).start()
        if workers > 0:
            Thread(target=self._cleanup_worker, name="cuemix-upload-cleanup", daemon=True).start()

    # ------------------------------------------------------------------
    # Redis-backed durability
    # ------------------------------------------------------------------

    def _persist(self, job: dict) -> None:
        """Best-effort mirror of one job's full record into Redis. Never
        raises -- an unreachable Redis degrades durability, not uploads
        themselves (same fail-open posture as channel_hub.py)."""

        client = get_sync_redis_client()
        if client is None:
            return
        try:
            client.set(_redis_job_key(job["job_id"]), json.dumps(job))
            client.sadd(_REDIS_ALL_JOBS_KEY, job["job_id"])
            if job.get("batch_id"):
                client.sadd(_redis_batch_key(job["batch_id"]), job["job_id"])
        except Exception:
            logger.warning("upload_queue: failed to persist job %s to redis", job["job_id"], exc_info=True)

    def _forget_redis(self, job: dict) -> None:
        client = get_sync_redis_client()
        if client is None:
            return
        try:
            client.delete(_redis_job_key(job["job_id"]))
            client.srem(_REDIS_ALL_JOBS_KEY, job["job_id"])
            if job.get("batch_id"):
                client.srem(_redis_batch_key(job["batch_id"]), job["job_id"])
        except Exception:
            logger.warning("upload_queue: failed to remove job %s from redis", job["job_id"], exc_info=True)

    def _recover(self) -> None:
        """Runs once at construction. Re-hydrates every job Redis still
        knows about into memory (so polling/history work immediately after a
        restart, not only once new jobs arrive), and re-enqueues anything
        that was still active when the previous process stopped -- reading
        its bytes back from the pending file, since in-memory state (and the
        original PriorityQueue tuple) didn't survive the restart."""

        client = get_sync_redis_client()
        if client is None:
            return
        try:
            job_ids = client.smembers(_REDIS_ALL_JOBS_KEY)
        except Exception:
            logger.warning("upload_queue: could not reach redis for crash recovery", exc_info=True)
            return

        recovered = 0
        for job_id in job_ids:
            try:
                raw = client.get(_redis_job_key(job_id))
            except Exception:
                continue
            if raw is None:
                continue
            try:
                job = json.loads(raw)
            except (TypeError, ValueError):
                continue

            if job.get("status") not in _ACTIVE_STATUSES:
                self._jobs[job_id] = job
                if job.get("batch_id"):
                    self._batches.setdefault(job["batch_id"], set()).add(job_id)
                continue

            pending_path = job.get("pending_path")
            if not pending_path or not Path(pending_path).is_file():
                # Was mid-flight when the process died and its raw bytes
                # didn't survive either -- nothing safe to redo, report it
                # plainly rather than silently dropping it or fabricating a
                # result.
                job["status"] = "failed"
                job["error"] = "Upload was interrupted by a restart and could not be recovered."
                self._jobs[job_id] = job
                if job.get("batch_id"):
                    self._batches.setdefault(job["batch_id"], set()).add(job_id)
                self._persist(job)
                continue

            job["status"] = "queued"
            job["error"] = None
            self._jobs[job_id] = job
            if job.get("batch_id"):
                self._batches.setdefault(job["batch_id"], set()).add(job_id)
            self._persist(job)
            self._queue.put_nowait((-job["priority"], next(self._sequence), job_id))
            recovered += 1

        if recovered:
            logger.warning(
                "upload_queue: recovered %d job(s) that were queued/in-flight before a restart", recovered
            )

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------

    def _new_job(
        self,
        owner_id: int,
        filename: str,
        content_type: str,
        priority: int,
        storage_subdir: str = "",
        batch_id: str | None = None,
        metadata: dict | None = None,
        max_size_override: int | None = None,
        on_stored_callback: str | None = None,
        deep_audio_validation: bool = False,
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
            "created_at_epoch": time(),
            "completed_at_monotonic": None,
            # Caller-scoped grouping (e.g. one bulk catalog upload) and
            # arbitrary caller metadata to carry through to materialization
            # time (e.g. track title/artist/visibility) -- both optional and
            # unused by the generic attachment path.
            "batch_id": batch_id,
            "metadata": dict(metadata) if metadata else None,
            "catalog_track_id": None,
            # Overrides ALLOWED_TYPES' cap for this job's re-validation in
            # the worker (see validate_upload) -- e.g. catalog uploads use a
            # higher, format-tiered cap than generic attachments.
            "max_size_override": max_size_override,
            # Durability: where this job's raw bytes are parked until
            # they're either moved to final storage or a retry consumes
            # them again. See submit()/_worker().
            "pending_path": None,
            "sha256": None,
            "on_stored_callback": on_stored_callback,
            # Opt-in, not automatic for every "audio" kind: this queue is
            # shared with generic forum/message/DM attachments
            # (routers/uploads.py), which never asked for (and would break
            # under) requirement 5's "actually decodable" bar -- only
            # routers/catalog.py's two upload paths set this.
            "deep_audio_validation": deep_audio_validation,
        }

    @staticmethod
    def _is_claimed(job: dict) -> bool:
        """A completed job is "claimed" once it's been materialized into a
        domain row -- an Attachment (generic uploads) or a CatalogTrack
        (catalog batch uploads). Only one of the two is ever set for a given
        job, depending on which router materialized it. .get() rather than
        direct indexing: hand-built job dicts (test fixtures predating
        catalog_track_id) shouldn't KeyError here."""

        return job.get("attachment_id") is not None or job.get("catalog_track_id") is not None

    def _prune(self) -> None:
        expired_files: list[str] = []
        pending_paths: list[str] = []
        forgettable: list[dict] = []
        with self._lock:
            now = monotonic()
            expired_unclaimed = [
                key
                for key, job in self._jobs.items()
                if job["status"] == "completed"
                and not self._is_claimed(job)
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
                    if key not in expired_unclaimed and job["status"] in _TERMINAL_STATUSES
                )
            for key in removable[: len(expired_unclaimed) + history_slots_needed]:
                job = self._jobs.pop(key, None)
                self._materialization_locks.pop(key, None)
                if job and job["status"] == "completed" and not self._is_claimed(job):
                    expired_files.append(job["result"]["storage_name"])
                # A job leaving tracking entirely can never be retried again,
                # so its pending copy (if the terminal state kept one, e.g.
                # a failed job retry never claimed) is worthless to keep.
                if job and job.get("pending_path"):
                    pending_paths.append(job["pending_path"])
                batch_id = job.get("batch_id") if job else None
                if batch_id:
                    members = self._batches.get(batch_id)
                    if members is not None:
                        members.discard(key)
                        if not members:
                            self._batches.pop(batch_id, None)
                if job:
                    forgettable.append(job)
        for storage_name in expired_files:
            try:
                (UPLOAD_DIR / storage_name).unlink(missing_ok=True)
            except OSError:
                # Capacity remains bounded even if an operator must later
                # remove an unreadable file manually.
                pass
        for pending_path in pending_paths:
            try:
                Path(pending_path).unlink(missing_ok=True)
            except OSError:
                pass
        for job in forgettable:
            self._forget_redis(job)

    def _cleanup_worker(self) -> None:
        """Expire unclaimed files even when no later submission arrives."""

        interval = max(60, min(300, self._unclaimed_ttl // 2))
        while not self._cleanup_wakeup.wait(interval):
            self._prune()

    def _write_pending(self, job_id: str, data: bytes) -> str:
        # mkdir here too, not just in __init__: tests (and any caller that
        # repoints UPLOAD_DIR after construction) swap it out from under an
        # already-constructed singleton, so the pending subdir under the new
        # path may never have been created otherwise.
        directory = UPLOAD_DIR / _PENDING_SUBDIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job_id}.bin"
        path.write_bytes(data)
        return str(path)

    def submit(
        self,
        owner_id: int,
        filename: str,
        content_type: str,
        data: bytes,
        priority: int,
        storage_subdir: str = "",
        batch_id: str | None = None,
        metadata: dict | None = None,
        max_size_override: int | None = None,
        on_stored_callback: str | None = None,
        deep_audio_validation: bool = False,
    ) -> dict:
        with self._submission_lock:
            self._prune()
            with self._lock:
                if len(self._jobs) >= self._max_history:
                    raise Full
            if self._queue.full():
                raise Full
            job = self._new_job(
                owner_id,
                filename,
                content_type,
                priority,
                storage_subdir,
                batch_id,
                metadata,
                max_size_override,
                on_stored_callback,
                deep_audio_validation,
            )
            job_id = job["job_id"]
            # Durable *before* this job is considered queued: bytes on disk
            # now, not only in the in-process queue tuple, is what lets a
            # crash between here and dispatch still be recoverable.
            job["pending_path"] = self._write_pending(job_id, data)
            job["sha256"] = hashlib.sha256(data).hexdigest()
            with self._lock:
                self._jobs[job_id] = job
                if batch_id:
                    self._batches.setdefault(batch_id, set()).add(job_id)
            self._persist(job)
            self._queue.put_nowait((-priority, next(self._sequence), job_id))
        _notify_status_listeners(job)
        return self.public(job_id)

    def submit_analysis(
        self, catalog_track_id: int, priority: int = 5, upload_job_id: str | None = None
    ) -> None:
        """Queue a post-store analysis task on the same worker pool.

        Fire-and-forget as far as the analysis result itself goes -- the
        caller already holds the catalog_track_id it queued and can read the
        CatalogTrack row's analysis_status directly. `upload_job_id`, if
        given, is how the *upload* job (still sitting in "analyzing") learns
        analysis finished -- see _run_analysis.
        """

        self._queue.put_nowait(
            (
                -priority,
                next(self._sequence),
                f"{_ANALYZE_PREFIX}{catalog_track_id}::{upload_job_id or ''}",
            )
        )

    def submit_external_analysis(self, external_track_id: int, priority: int = 5) -> None:
        """Queue a first-time (or retry) Audius analysis task on the same
        worker pool as everything else in this module -- see
        _ANALYZE_EXTERNAL_PREFIX's own comment. Fire-and-forget: the caller
        (pipeline/external_track_cache.py) already holds the
        external_track_id it just created/is retrying and can read that
        row's analysis_status directly for the result; there is no
        associated upload job to notify the way submit_analysis's
        upload_job_id can."""

        self._queue.put_nowait(
            (-priority, next(self._sequence), f"{_ANALYZE_EXTERNAL_PREFIX}{external_track_id}")
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
            jobs = [
                self._new_job(owner_id, filename, content_type, priority)
                for owner_id, filename, content_type, _, priority in items
            ]
            for job, (_, _, _, data, _priority) in zip(jobs, items):
                job["pending_path"] = self._write_pending(job["job_id"], data)
                job["sha256"] = hashlib.sha256(data).hexdigest()
            with self._lock:
                self._jobs.update({job["job_id"]: job for job in jobs})
            try:
                for job, (_, _, _, _data, priority) in zip(jobs, items):
                    self._queue.put_nowait((-priority, next(self._sequence), job["job_id"]))
            except Full:
                # This is only defensive: other producers are serialized and
                # consumers can only free capacity after the check.
                with self._lock:
                    for job in jobs:
                        self._jobs.pop(job["job_id"], None)
                raise
            for job in jobs:
                self._persist(job)
        return [self.public(job["job_id"]) for job in jobs]

    def public(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def jobs_for_batch(self, batch_id: str) -> list[dict]:
        """Every still-tracked job submitted under this batch_id, in
        submission order. Jobs that already aged out of history (see
        _prune's UPLOAD_JOB_TTL_SECONDS/max_history bounds) are simply
        absent -- there is no separate durable batch record beyond what
        Redis already mirrors of each job."""

        with self._lock:
            job_ids = self._batches.get(batch_id, set())
            jobs = [self._jobs[job_id] for job_id in job_ids if job_id in self._jobs]
        jobs.sort(key=lambda job: job["created_at_monotonic"])
        return [dict(job) for job in jobs]

    def batch_size_so_far(self, batch_id: str) -> int:
        """How many jobs already exist under this batch_id -- used to derive
        a new submission's fair-share priority (see routers/catalog.py)
        before that submission itself is added."""

        with self._lock:
            return len(self._batches.get(batch_id, ()))

    def set_attachment(self, job_id: str, attachment_id: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["attachment_id"] = attachment_id
                snapshot = dict(job)
            else:
                snapshot = None
        if snapshot:
            self._persist(snapshot)

    def set_catalog_track(self, job_id: str, catalog_track_id: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["catalog_track_id"] = catalog_track_id
                snapshot = dict(job)
            else:
                snapshot = None
        if snapshot:
            self._persist(snapshot)

    def _set_status(self, job_id: str, status: str, *, error: str | None = None, completed: bool = False) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job["status"] = status
            job["error"] = error
            if completed:
                job["completed_at_monotonic"] = monotonic()
            snapshot = dict(job)
        self._persist(snapshot)
        _notify_status_listeners(snapshot)
        return snapshot

    def retry_job(self, job_id: str, owner_id: int) -> dict | None:
        """Re-queues a job that finished "failed", reusing the same bytes
        (still on disk in its pending location) and the same priority.
        Returns None if the job doesn't exist, isn't owned by this caller,
        isn't currently failed, or its pending bytes are gone (already
        cleaned up -- nothing safe to retry)."""

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["owner_id"] != owner_id or job["status"] != "failed":
                return None
            pending_path = job.get("pending_path")
            if not pending_path or not Path(pending_path).is_file():
                return None
            job["status"] = "queued"
            job["error"] = None
            priority = job["priority"]
            snapshot = dict(job)
        self._persist(snapshot)
        self._queue.put_nowait((-priority, next(self._sequence), job_id))
        _notify_status_listeners(snapshot)
        return self.public(job_id)

    def cancel_job(self, job_id: str, owner_id: int) -> bool:
        """Cancels a job that's still "queued" (lazy deletion: a plain
        PriorityQueue can't remove an arbitrary entry, so the worker itself
        checks for "cancelled" immediately after dequeuing and skips it).
        Returns False if the job doesn't exist, isn't owned by this caller,
        or has already left "queued" (a job already being validated/stored/
        analyzed has gone too far to cleanly cancel)."""

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["owner_id"] != owner_id or job["status"] != "queued":
                return False
            job["status"] = "cancelled"
            pending_path = job.get("pending_path")
            snapshot = dict(job)
        self._persist(snapshot)
        if pending_path:
            try:
                Path(pending_path).unlink(missing_ok=True)
            except OSError:
                pass
        _notify_status_listeners(snapshot)
        return True

    def mark_completed(self, job_id: str) -> None:
        """Lets an on_stored_callback declare its job fully done without
        going through submit_analysis -- e.g. routers/catalog.py's
        checksum-dedup path, where an upload reuses an existing track's
        already-computed analysis and has no more async work left to do.
        A no-op if the job doesn't exist (already pruned, unknown id)."""

        self._set_status(job_id, "completed", completed=True)

    def materialization_lock(self, job_id: str) -> Lock:
        """Serialize Attachment/CatalogTrack row creation for concurrent
        status polls."""

        with self._lock:
            return self._materialization_locks.setdefault(job_id, Lock())

    def _worker(self) -> None:
        while True:
            _, _, job_id = self._queue.get()
            if job_id.startswith(_ANALYZE_EXTERNAL_PREFIX):
                external_track_id_text = job_id[len(_ANALYZE_EXTERNAL_PREFIX):]
                self._run_external_analysis(external_track_id_text)
                self._queue.task_done()
                continue

            if job_id.startswith(_ANALYZE_PREFIX):
                payload = job_id[len(_ANALYZE_PREFIX):]
                track_id_text, _, upload_job_id = payload.partition("::")
                self._run_analysis(track_id_text, upload_job_id or None)
                self._queue.task_done()
                continue

            with self._lock:
                job = self._jobs.get(job_id)
            if job is None or job["status"] == "cancelled":
                self._queue.task_done()
                continue

            self._set_status(job_id, "validating")
            pending_path = Path(job["pending_path"])
            try:
                data = pending_path.read_bytes()
            except OSError as exc:
                self._set_status(job_id, "failed", error=f"Upload data is missing: {exc}")
                self._queue.task_done()
                continue

            try:
                kind, extension, _ = validate_upload(
                    job["filename"], job["content_type"], data, job.get("max_size_override")
                )
                if kind == "audio" and job.get("deep_audio_validation"):
                    _validate_decodable_audio(data, extension)
            except ValueError as exc:
                self._set_status(job_id, "failed", error=str(exc))
                self._queue.task_done()
                continue

            self._set_status(job_id, "storing")
            storage_name = f"{uuid4().hex}{extension}"
            target_dir = UPLOAD_DIR / job["storage_subdir"] if job["storage_subdir"] else UPLOAD_DIR
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                path = target_dir / storage_name
                path.write_bytes(data)
                pending_path.unlink(missing_ok=True)
            except OSError as exc:
                self._set_status(job_id, "failed", error=str(exc))
                self._queue.task_done()
                continue

            result = {
                "kind": kind,
                "storage_name": storage_name,
                "size_bytes": len(data),
                "sha256": job.get("sha256") or hashlib.sha256(data).hexdigest(),
            }
            with self._lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current["result"] = result
                    snapshot = dict(current)
                else:
                    snapshot = None
            if snapshot:
                self._persist(snapshot)

            callback_name = job.get("on_stored_callback")
            if callback_name:
                fn = _CALLBACKS.get(callback_name)
                if fn is None:
                    self._set_status(job_id, "failed", error=f"No handler registered for '{callback_name}'.")
                else:
                    self._set_status(job_id, "analyzing")
                    try:
                        fn(job_id)
                    except Exception:
                        logger.exception(
                            "on_stored callback '%s' failed for job %s", callback_name, job_id
                        )
                        self._set_status(job_id, "failed", error="Could not finish cataloging this upload.")
            else:
                self._set_status(job_id, "completed", completed=True)
            self._queue.task_done()

    def _run_external_analysis(self, external_track_id_text: str) -> None:
        try:
            external_track_id = int(external_track_id_text)
            # Imported lazily, same reasoning as _run_analysis's own
            # librosa-adjacent import below: keep this module's own import
            # cheap for callers that never trigger an analysis job.
            from app.services.audio_analysis import analyze_external_track

            analyze_external_track(external_track_id)
        except Exception:
            logger.exception(
                "External track analysis job failed for id=%s", external_track_id_text
            )

    def _run_analysis(self, catalog_track_id_text: str, upload_job_id: str | None) -> None:
        catalog_track_id: int | None = None
        try:
            catalog_track_id = int(catalog_track_id_text)
            # Imported lazily so importing this module never pulls in
            # librosa's heavy dependency tree unless an analysis task
            # actually runs.
            from app.services.audio_analysis import analyze_catalog_track

            analyze_catalog_track(catalog_track_id)
        except Exception:
            logger.exception("Catalog track analysis job failed for id=%s", catalog_track_id_text)
        finally:
            if upload_job_id:
                # Callbacks run *before* the status flips to "completed", not
                # after: "completed" is the signal callers (and tests
                # draining the queue between runs) treat as "every write this
                # job will ever make has already happened" -- if a
                # callback's own DB write (e.g. the "ready in your catalog"
                # notification) landed after that flip, a caller that
                # stopped waiting the moment it saw "completed" could still
                # race against it.
                for fn in _ANALYSIS_COMPLETE_CALLBACKS.values():
                    try:
                        fn(upload_job_id, catalog_track_id)
                    except Exception:
                        logger.exception(
                            "analysis-complete callback failed for job %s", upload_job_id
                        )
                self._set_status(upload_job_id, "completed", completed=True)


upload_queue = UploadQueue(
    workers=max(1, min(8, int(os.getenv("UPLOAD_WORKERS", "4")))),
    capacity=max(1, min(256, int(os.getenv("UPLOAD_QUEUE_CAPACITY", "32")))),
)
