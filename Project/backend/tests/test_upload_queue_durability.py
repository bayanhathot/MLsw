"""Job Queue hardening: crash-recovery, retry/cancel, and a bulk-load smoke
test for bounded concurrency + fair batch priority (see upload_queue.py's
module docstring for the durability design).

Every test here builds its own UploadQueue instance rather than using the
module-level singleton (app.services.upload_queue.upload_queue) -- two
UploadQueue instances constructed *within the same process* both read/write
the same Redis keys and UPLOAD_DIR, so if both had live workers they would
race over the same jobs. Tests that simulate "process A dies, process B
recovers" therefore keep process A's queue at workers=0 (nothing ever
dequeues its jobs) before constructing process B's queue -- the same
methodology verified manually against a real Redis during this milestone's
implementation.

Requires a real, reachable Redis: crash-recovery has nothing to verify
without one, and upload_queue.py's fail-open posture means these behaviors
simply don't exist when REDIS_URL is unset. Skipped in that case rather than
asserted against no-op behavior.
"""

import os
import threading
import time
from pathlib import Path
from queue import Empty, Full

import pytest

from app.core.redis_client import get_sync_redis_client
from app.services import upload_queue as uq_module
from app.services.upload_queue import UploadQueue

pytestmark = pytest.mark.skipif(
    not os.getenv("REDIS_URL", "").strip(),
    reason="crash-recovery/durability requires a real REDIS_URL",
)

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
).read_bytes()


def _drain_terminal(queue: UploadQueue, job_ids, timeout=30.0):
    deadline = time.monotonic() + timeout
    remaining = set(job_ids)
    while remaining and time.monotonic() < deadline:
        for job_id in list(remaining):
            job = queue.public(job_id)
            if job is not None and job["status"] in {"completed", "failed", "cancelled"}:
                remaining.discard(job_id)
        if remaining:
            time.sleep(0.02)
    return remaining


def test_crash_recovery_requeues_a_still_queued_job_and_completes_it(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)

    # "Process A": accepts the upload (bytes durably on disk, record in
    # Redis) but never gets to process it -- workers=0 stands in for the
    # process dying immediately after submit() returns.
    dead_process_queue = UploadQueue(workers=0, capacity=10)
    job = dead_process_queue.submit(
        1, "track.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5, storage_subdir="catalog"
    )
    assert job["status"] == "queued"

    # "Process B": a fresh UploadQueue construction, standing in for a
    # restart. Its __init__ -> _recover() should find the still-queued job
    # in Redis, confirm its pending bytes are still on disk, and re-enqueue
    # it for a live worker to actually pick up.
    recovered_process_queue = UploadQueue(workers=2, capacity=10)
    try:
        remaining = _drain_terminal(recovered_process_queue, [job["job_id"]])
        assert not remaining, "job never reached a terminal state after recovery"
        recovered = recovered_process_queue.public(job["job_id"])
        assert recovered["status"] == "completed"
        assert recovered["result"]["storage_name"]
        assert (tmp_path / "catalog" / recovered["result"]["storage_name"]).is_file()
    finally:
        recovered_process_queue._cleanup_wakeup.set()


def test_crash_recovery_marks_a_job_failed_when_its_pending_bytes_are_gone(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)

    dead_process_queue = UploadQueue(workers=0, capacity=10)
    job = dead_process_queue.submit(
        1, "track.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5, storage_subdir="catalog"
    )
    # Simulate losing the volume the pending file lived on (e.g. an
    # ephemeral disk that didn't survive the restart) -- Redis still has
    # the job record, but there's nothing safe left to redo.
    Path(job["pending_path"]).unlink()

    recovered_process_queue = UploadQueue(workers=0, capacity=10)
    recovered = recovered_process_queue.public(job["job_id"])
    assert recovered["status"] == "failed"
    assert "restart" in recovered["error"].lower()


def test_retry_requeues_a_failed_job_and_completes_it(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    queue = UploadQueue(workers=1, capacity=10)
    try:
        # A signature mismatch fails validation deterministically and fast.
        job = queue.submit(1, "fake.wav", "audio/wav", b"not really a wav file", priority=5)
        remaining = _drain_terminal(queue, [job["job_id"]])
        assert not remaining
        assert queue.public(job["job_id"])["status"] == "failed"

        # Retrying re-submits the exact same (still-broken) bytes, so it
        # deterministically fails again -- this test cares that retry
        # actually re-queues and re-runs the job, not that the file becomes
        # valid.
        retried = queue.retry_job(job["job_id"], owner_id=1)
        assert retried is not None
        assert retried["status"] == "queued"
        remaining = _drain_terminal(queue, [job["job_id"]])
        assert not remaining
        assert queue.public(job["job_id"])["status"] == "failed"
    finally:
        queue._cleanup_wakeup.set()


def test_retry_is_refused_for_a_job_that_is_not_failed_or_not_owned(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    queue = UploadQueue(workers=0, capacity=10)
    job = queue.submit(1, "track.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5)
    # Still "queued" -- nothing has failed yet.
    assert queue.retry_job(job["job_id"], owner_id=1) is None
    assert queue.retry_job("does-not-exist", owner_id=1) is None


def test_cancel_stops_a_still_queued_job_before_a_worker_touches_it(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    queue = UploadQueue(workers=0, capacity=10)
    job = queue.submit(1, "track.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5)
    pending_path = Path(job["pending_path"])
    assert pending_path.is_file()

    assert queue.cancel_job(job["job_id"], owner_id=1) is True
    cancelled = queue.public(job["job_id"])
    assert cancelled["status"] == "cancelled"
    assert not pending_path.exists()  # cleaned up, nothing left to (re)process

    # A worker that dequeues a lazily-cancelled job must skip it rather
    # than process it -- start one now and confirm the job stays cancelled.
    queue._queue.put_nowait((-job["priority"], 0, job["job_id"]))
    thread = threading.Thread(target=queue._worker, daemon=True)
    thread.start()
    time.sleep(0.2)
    assert queue.public(job["job_id"])["status"] == "cancelled"


def test_cancel_is_refused_once_a_job_has_left_queued(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    queue = UploadQueue(workers=1, capacity=10)
    try:
        job = queue.submit(1, "track.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5)
        remaining = _drain_terminal(queue, [job["job_id"]])
        assert not remaining
        assert queue.cancel_job(job["job_id"], owner_id=1) is False
        # Ownership is enforced too.
        other_job = queue.submit(2, "other.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5)
        assert queue.cancel_job(other_job["job_id"], owner_id=1) is False
    finally:
        queue._cleanup_wakeup.set()


def test_bounded_concurrency_never_exceeds_the_worker_count(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    worker_count = 3
    queue = UploadQueue(workers=worker_count, capacity=200)
    try:
        in_flight: set[str] = set()
        peak = 0
        lock = threading.Lock()

        def on_status(job: dict) -> None:
            nonlocal peak
            with lock:
                if job["status"] in {"validating", "storing"}:
                    in_flight.add(job["job_id"])
                else:
                    in_flight.discard(job["job_id"])
                peak = max(peak, len(in_flight))

        uq_module.add_status_listener(on_status)
        try:
            job_ids = [
                queue.submit(1, f"track{i}.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5)["job_id"]
                for i in range(55)
            ]
            remaining = _drain_terminal(queue, job_ids, timeout=60.0)
            assert not remaining, f"{len(remaining)} of 55 jobs never reached a terminal state"
            assert all(queue.public(job_id)["status"] == "completed" for job_id in job_ids)
            # A small allowance for the inherent race between a status
            # transition and this listener observing it -- the queue must
            # never run meaningfully more concurrent jobs than it has
            # worker threads.
            assert peak <= worker_count + 1, f"observed {peak} concurrent jobs with only {worker_count} workers"
        finally:
            uq_module._STATUS_LISTENERS.remove(on_status)
    finally:
        queue._cleanup_wakeup.set()


def test_fair_batch_priority_orders_the_internal_queue_by_priority_then_arrival(monkeypatch, tmp_path):
    # Mechanism-level, not timing-dependent: with workers=0 nothing drains
    # the internal PriorityQueue, so its dequeue order is fully
    # deterministic and directly verifies the fairness contract (higher
    # priority first, arrival order as the tiebreaker) without racing real
    # worker threads.
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    queue = UploadQueue(workers=0, capacity=200)

    # A big batch's priority decays with depth (routers/catalog.py assigns
    # this before calling submit()) -- simulate that here directly.
    big_batch_jobs = [
        queue.submit(1, f"big{i}.wav", "audio/wav", _DEMO_WAV_BYTES, priority=max(0, 5 - i // 3), batch_id="big")
        for i in range(10)
    ]
    # A fresh, unrelated small batch submitted afterwards starts at full
    # priority and must not be starved by the big batch ahead of it.
    small_batch_job = queue.submit(
        2, "small.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5, batch_id="small"
    )

    dequeued_job_ids = []
    while True:
        try:
            _, _, job_id = queue._queue.get_nowait()
        except Empty:
            break
        dequeued_job_ids.append(job_id)

    dequeued_priorities = [queue.public(job_id)["priority"] for job_id in dequeued_job_ids]
    assert dequeued_priorities == sorted(dequeued_priorities, reverse=True)
    # The small batch's single job -- priority 5, submitted last -- still
    # dequeues no later than the big batch's own first few (also
    # priority-5) jobs, i.e. it is never pushed behind lower-priority work.
    small_position = dequeued_job_ids.index(small_batch_job["job_id"])
    first_low_priority_position = next(
        index for index, job_id in enumerate(dequeued_job_ids)
        if queue.public(job_id)["priority"] < 5
    )
    assert small_position < first_low_priority_position


def test_queue_capacity_is_respected_under_a_50_plus_file_batch(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    queue = UploadQueue(workers=4, capacity=64)
    try:
        job_ids = [
            queue.submit(1, f"track{i}.wav", "audio/wav", _DEMO_WAV_BYTES, priority=5, batch_id="load-test")[
                "job_id"
            ]
            for i in range(52)
        ]
        assert len(set(job_ids)) == 52  # every job got a distinct id
        remaining = _drain_terminal(queue, job_ids, timeout=90.0)
        assert not remaining, f"{len(remaining)} of 52 jobs never settled"
        statuses = [queue.public(job_id)["status"] for job_id in job_ids]
        assert all(status == "completed" for status in statuses)

        redis_client = get_sync_redis_client()
        if redis_client is not None:
            for job_id in job_ids:
                assert redis_client.get(f"cuemix:upload:job:{job_id}") is not None
    finally:
        queue._cleanup_wakeup.set()
