"""Bulk catalog upload: POST /catalog/tracks/batch-jobs (enqueue, per-file,
never blocks) + GET .../batch-jobs/{id} and .../batches/{id} (poll). Each
job's CatalogTrack row is created *eagerly*, by upload_queue.py's worker
invoking routers/catalog.py's on_stored_callback the moment the file's
bytes finish storing -- not lazily on poll -- so a job's own status
progresses queued -> validating -> storing -> analyzing -> completed/
failed/cancelled (see routers/catalog.py's module docstring)."""

import time
import uuid
from pathlib import Path

from conftest import register_and_login

from app.database.models.catalog import CatalogTrack
from app.routers.catalog import _BATCH_PRIORITY_DECAY_EVERY

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
).read_bytes()

_ACTIVE_STATUSES = ("queued", "validating", "storing", "analyzing")


def _batch_id():
    return f"test-batch-{uuid.uuid4().hex}"


def _enqueue(client, batch_id, filename="track.wav", content_type="audio/wav", data=None, **overrides):
    fields = {"batch_id": batch_id, "title": "Test Track", "album": "Test Album", "artist": "The Testers"}
    fields.update(overrides)
    return client.post(
        "/catalog/tracks/batch-jobs",
        data=fields,
        files={"file": (filename, data if data is not None else _DEMO_WAV_BYTES, content_type)},
    )


def _poll_batch_until_settled(client, batch_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        response = client.get(f"/catalog/tracks/batches/{batch_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if all(body[status] == 0 for status in _ACTIVE_STATUSES):
            return body
        time.sleep(0.02)
    return body


def test_enqueue_returns_immediately_without_blocking_the_request(client):
    register_and_login(client)
    response = _enqueue(client, _batch_id())
    assert response.status_code == 202, response.text
    body = response.json()
    # Materialization races the response on a worker thread -- what matters
    # here is that the request itself never blocks on storage/analysis, not
    # which exact status won the race.
    assert body["status"] != "failed"
    assert body["job_id"]


def test_batch_completes_and_materializes_tracks_via_polling(client, db_session):
    register_and_login(client)
    batch_id = _batch_id()
    first = _enqueue(client, batch_id, title="Song One").json()
    second = _enqueue(client, batch_id, title="Song Two").json()
    assert first["job_id"] != second["job_id"]

    body = _poll_batch_until_settled(client, batch_id)
    assert body["total"] == 2
    assert body["completed"] == 2
    assert body["failed"] == 0
    assert body["cancelled"] == 0
    titles = {item["track"]["title"] for item in body["jobs"]}
    assert titles == {"Song One", "Song Two"}

    for item in body["jobs"]:
        row = db_session.query(CatalogTrack).filter_by(id=item["track"]["id"]).first()
        assert row is not None
        assert row.checksum_sha256 is not None
        assert row.visibility == "public"


def test_a_bad_file_in_a_batch_is_rejected_without_affecting_the_rest(client):
    # A signature mismatch is cheap enough to catch synchronously (same
    # fail-fast behavior POST /catalog/tracks already had) -- it 422s its
    # own request immediately rather than silently failing later, but
    # crucially never touches any other file already queued under the same
    # batch_id, matching "reject individually, never fail the batch."
    register_and_login(client)
    batch_id = _batch_id()
    good = _enqueue(client, batch_id, title="Good Song")
    bad = _enqueue(
        client,
        batch_id,
        filename="fake.wav",
        data=b"not really a wav file",
        title="Bad Song",
    )
    assert good.status_code == 202
    assert bad.status_code == 422
    assert "signature" in bad.json()["detail"].lower()

    body = _poll_batch_until_settled(client, batch_id)
    assert body["total"] == 1  # the rejected file was never enqueued at all
    assert body["completed"] == 1
    assert body["failed"] == 0
    assert body["jobs"][0]["track"]["title"] == "Good Song"


def test_batch_priority_decays_with_batch_depth(client):
    register_and_login(client)
    batch_id = _batch_id()
    # One request at a time so batch_size_so_far() reflects each prior
    # submission -- concurrent submission ordering isn't what this test is
    # about, only that the *assigned* priority follows the documented decay.
    priorities = [_enqueue(client, batch_id, title=f"Song {i}").json()["priority"] for i in range(2 * _BATCH_PRIORITY_DECAY_EVERY + 1)]
    expected = [max(0, 5 - i // _BATCH_PRIORITY_DECAY_EVERY) for i in range(len(priorities))]
    assert priorities == expected
    # A fresh, unrelated batch is not penalized by an earlier large one.
    fresh_priority = _enqueue(client, _batch_id(), title="Unrelated").json()["priority"]
    assert fresh_priority == 5


def test_batch_and_job_status_are_scoped_to_the_owner(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    batch_id = _batch_id()
    job = _enqueue(client, batch_id, title="Alice's Song").json()

    assert second_client.get(f"/catalog/tracks/batch-jobs/{job['job_id']}").status_code == 404
    assert second_client.get(f"/catalog/tracks/batches/{batch_id}").status_code == 404
    # The owner can still see it.
    assert client.get(f"/catalog/tracks/batch-jobs/{job['job_id']}").status_code == 200
    assert client.get(f"/catalog/tracks/batches/{batch_id}").status_code == 200


def test_completed_job_status_reuses_the_request_database_session(client, monkeypatch):
    """Regression for the 20-user production stress gate.

    Authentication already checks out one connection for the request. Opening
    another SessionLocal while serializing every completed upload can exhaust
    SQLAlchemy's 5 + 10 connection pool when 20 users poll concurrently.
    """

    register_and_login(client)
    batch_id = _batch_id()
    job = _enqueue(client, batch_id).json()
    settled = _poll_batch_until_settled(client, batch_id)
    assert settled["completed"] == 1

    def unexpected_second_session():
        raise AssertionError("job status opened a second database session")

    monkeypatch.setattr("app.database.database.SessionLocal", unexpected_second_session)

    response = client.get(f"/catalog/tracks/batch-jobs/{job['job_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["track"]["title"] == "Test Track"


def test_unknown_batch_and_job_id_are_404(client):
    register_and_login(client)
    assert client.get("/catalog/tracks/batches/does-not-exist").status_code == 404
    assert client.get("/catalog/tracks/batch-jobs/does-not-exist").status_code == 404


def test_batch_upload_requires_title_album_and_artist(client):
    register_and_login(client)
    assert _enqueue(client, _batch_id(), title="").status_code == 422
    assert _enqueue(client, _batch_id(), album="").status_code == 422
    assert _enqueue(client, _batch_id(), artist="").status_code == 422
