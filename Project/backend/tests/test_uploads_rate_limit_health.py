import asyncio
import time
import base64
from collections import deque
from queue import Full
import sys
from types import SimpleNamespace
from urllib.parse import quote

from conftest import register_and_login
from fastapi import HTTPException
import pytest
from starlette.requests import Request

from app.core.rate_limit import RateLimiter
from app.core.config import cors_origins, public_api_url
from app import cleanup_uploads
from app.routers.uploads import _decode_filename, _read_limited_body
from app.services.upload_queue import UploadQueue, validate_upload


def test_upload_magic_validation_and_private_serving(client, second_client):
    register_and_login(client)
    response = client.post(
        "/uploads/jobs?priority=9",
        content=b"not really an mp3",
        headers={"Content-Type": "audio/mpeg", "X-Filename": "fake.mp3"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    for _ in range(100):
        result = client.get(f"/uploads/jobs/{job_id}").json()
        if result["status"] in {"failed", "completed"}:
            break
        time.sleep(0.005)
    assert result["status"] == "failed"
    assert "signature" in result["error"].lower()

    valid = client.post(
        "/uploads/jobs",
        content=b"ID3" + b"\x00" * 32,
        headers={"Content-Type": "audio/mpeg", "X-Filename": "clip.mp3"},
    ).json()
    for _ in range(100):
        valid = client.get(f"/uploads/jobs/{valid['job_id']}").json()
        if valid["status"] == "completed" and valid["attachment"]:
            break
        time.sleep(0.005)
    assert valid["attachment"]["kind"] == "audio"
    repeated = client.get(f"/uploads/jobs/{valid['job_id']}").json()
    assert repeated["attachment"]["id"] == valid["attachment"]["id"]
    path = valid["attachment"]["url"].removeprefix("/api")
    served = client.get(path)
    assert served.status_code == 200
    assert served.headers["content-disposition"].startswith("inline")
    assert served.headers["cache-control"] == "private, no-store"
    register_and_login(second_client, "bob", "bob@example.com")
    assert second_client.get(path).status_code == 403
    assert second_client.delete(path).status_code == 403
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404


def test_upload_declared_size_and_queue_backpressure(client):
    register_and_login(client)
    too_large = client.post(
        "/uploads/jobs",
        content=b"ID3",
        headers={
            "Content-Type": "audio/mpeg",
            "X-Filename": "large.mp3",
            "Content-Length": str(11 * 1024 * 1024),
        },
    )
    assert too_large.status_code == 413

    queue = UploadQueue(workers=0, capacity=1)
    queue.submit(1, "one.mp3", "audio/mpeg", b"ID3x", 5)
    try:
        queue.submit(1, "two.mp3", "audio/mpeg", b"ID3x", 5)
    except Full:
        pass
    else:
        raise AssertionError("Bounded queue accepted work beyond its capacity")


def test_wav_attachment_around_30mb_is_accepted():
    # Compressed (mp3/ogg) and lossless (wav/flac) formats need different
    # ceilings for the same clip length -- a 3-minute uncompressed WAV is
    # already ~31 MB, comfortably over the old flat 10 MiB cap but well
    # under the new 100 MiB lossless default (ATTACHMENT_AUDIO_MAX_MB_LOSSLESS,
    # read at module import so not env-overridable from inside a test).
    # Signature-valid bytes only (not real decodable audio): the generic
    # attachment path never runs deep audio validation, only the cheap
    # signature/size check this exercises.
    data = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * (30 * 1024 * 1024)
    kind, extension, max_size = validate_upload("clip.wav", "audio/wav", data)
    assert kind == "audio"
    assert extension == ".wav"
    assert max_size == 100 * 1024 * 1024


def test_wav_attachment_over_its_cap_is_rejected_with_a_per_format_message():
    data = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * (101 * 1024 * 1024)
    with pytest.raises(ValueError, match=r"exceeds the 100 MiB cap for WAV"):
        validate_upload("clip.wav", "audio/wav", data)


def test_mp3_attachment_over_its_smaller_cap_is_still_rejected():
    # MP3/OGG keep the old, much lower ceiling -- a file that would fit
    # comfortably under WAV/FLAC's new 100 MiB cap must still be rejected
    # here, with a message naming *this* format's own cap, not WAV's.
    data = b"ID3" + b"\x00" * (11 * 1024 * 1024)
    with pytest.raises(ValueError, match=r"exceeds the 10 MiB cap for MP3"):
        validate_upload("clip.mp3", "audio/mpeg", data)


def test_streaming_upload_reader_stops_at_limit():
    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"5678", "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/uploads/jobs",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
            "query_string": b"",
        },
        receive,
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_read_limited_body(request, 5))
    assert exc_info.value.status_code == 413


def test_percent_encoded_unicode_upload_filename_is_decoded():
    filename = "موسيقى 🎵.mp3"
    assert _decode_filename(quote(filename, safe="")) == filename
    with pytest.raises(HTTPException) as exc_info:
        _decode_filename("broken%ZZname.mp3")
    assert exc_info.value.status_code == 422


def test_attached_media_cannot_be_deleted_directly_and_post_cleanup_removes_it(client):
    register_and_login(client)
    job = client.post(
        "/uploads/jobs",
        content=b"ID3" + b"\x00" * 16,
        headers={"Content-Type": "audio/mpeg", "X-Filename": "post.mp3"},
    ).json()
    for _ in range(100):
        job = client.get(f"/uploads/jobs/{job['job_id']}").json()
        if job["status"] == "completed" and job["attachment"]:
            break
        time.sleep(0.005)
    attachment = job["attachment"]
    post = client.post(
        "/posts",
        json={
            "title": "With media",
            "body": "Attachment lifecycle",
            "attachment_ids": [attachment["id"]],
        },
    ).json()
    path = attachment["url"].removeprefix("/api")
    assert client.delete(path).status_code == 409
    assert client.delete(f"/posts/{post['id']}").status_code == 204
    assert client.get(path).status_code == 404


def test_batch_validation_and_capacity_are_atomic(client, monkeypatch):
    register_and_login(client)
    queue = UploadQueue(workers=0, capacity=1)
    monkeypatch.setattr("app.routers.uploads.upload_queue", queue)
    encoded = base64.b64encode(b"ID3x").decode()
    response = client.post(
        "/uploads/batch",
        json={
            "files": [
                {"filename": "one.mp3", "content_type": "audio/mpeg", "data_base64": encoded},
                {"filename": "two.mp3", "content_type": "audio/mpeg", "data_base64": encoded},
            ]
        },
    )
    assert response.status_code == 503
    assert queue._jobs == {}

    invalid = client.post(
        "/uploads/batch",
        json={
            "files": [
                {"filename": "one.mp3", "content_type": "audio/mpeg", "data_base64": encoded},
                {"filename": "bad.mp3", "content_type": "audio/mpeg", "data_base64": base64.b64encode(b"bad").decode()},
            ]
        },
    )
    assert invalid.status_code == 422
    assert queue._jobs == {}


def test_queue_prunes_expired_unclaimed_files(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.upload_queue.UPLOAD_DIR", tmp_path)
    # TTL cleanup is independent from history pressure.
    queue = UploadQueue(workers=0, capacity=2, max_history=1000)
    orphan = tmp_path / "orphan.mp3"
    orphan.write_bytes(b"ID3x")
    queue._jobs["old"] = {
        "job_id": "old",
        "owner_id": 1,
        "filename": "old.mp3",
        "content_type": "audio/mpeg",
        "priority": 1,
        "status": "completed",
        "error": None,
        "result": {"storage_name": orphan.name},
        "attachment_id": None,
        "created_at_monotonic": 0.0,
        "completed_at_monotonic": 0.0,
    }
    queue._unclaimed_ttl = 1
    queue._prune()
    assert queue._jobs == {}
    assert not orphan.exists()


def test_orphan_deletion_requires_backend_stopped_confirmation(monkeypatch):
    monkeypatch.delenv("DELETE_ORPHAN_UPLOADS", raising=False)
    monkeypatch.setattr(sys, "argv", ["cleanup_uploads", "--delete"])
    with pytest.raises(SystemExit, match="Refusing deletion"):
        cleanup_uploads.main()


def test_rate_limiter_does_not_trust_spoofed_forwarded_header(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    limiter = RateLimiter(requests=1, window_seconds=60)

    def request(forwarded):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/auth/login",
                "headers": [(b"x-forwarded-for", forwarded.encode())],
                "client": ("127.0.0.1", 1234),
                "server": ("test", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    limiter(request("1.1.1.1"))
    try:
        limiter(request("2.2.2.2"))
    except HTTPException as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("Spoofed X-Forwarded-For bypassed the limiter")


def test_rate_limiter_uses_route_template_and_prunes_inactive_keys(monkeypatch):
    # D6b: RateLimiter checks Redis first when REDIS_URL is configured (see
    # app/core/rate_limit.py) -- this test exercises the process-local
    # fallback's own pruning behavior specifically, so it forces that path
    # regardless of whether this environment happens to have a real Redis
    # available (test_uploads_rate_limit_health.py's other rate-limit test
    # doesn't care which path runs, since both enforce the same limit).
    monkeypatch.setattr("app.core.rate_limit.get_sync_redis_client", lambda: None)
    limiter = RateLimiter(requests=1, window_seconds=60)

    def request(path, route_path, client="127.0.0.1"):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "route": SimpleNamespace(path=route_path),
                "headers": [],
                "client": (client, 1234),
                "server": ("test", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    limiter(request("/posts/1/vote", "/posts/{post_id}/vote"))
    with pytest.raises(HTTPException) as exc_info:
        limiter(request("/posts/999/vote", "/posts/{post_id}/vote"))
    assert exc_info.value.status_code == 429

    limiter._events["expired:203.0.113.1"] = deque()
    limiter._last_prune = 0
    monkeypatch.setattr("app.core.rate_limit.monotonic", lambda: 10_000)
    limiter(request("/posts", "/posts", client="127.0.0.2"))
    assert "expired:203.0.113.1" not in limiter._events


def test_health_and_request_id(client):
    response = client.get("/health", headers={"X-Request-ID": "test-request"})
    assert response.json() == {"service": "cuemix-backend", "status": "healthy", "version": "0.2.0"}
    assert response.headers["x-request-id"] == "test-request"
    model = client.get("/model-info").json()
    assert model["selector"] == "deterministic-intent-v1"
    assert model["llm_provider"] == "none"
    assert model["llm_configured"] is False
    assert model["llm_availability"] == "not_configured"
    audio = client.get("/static/audio/cuemix-demo.wav")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


def test_static_mount_never_requires_a_root_path_prefix(client):
    """Regression guard for a real bug: FastAPI(root_path="/api") broke
    every request under the /static Mount specifically (not regular
    routes -- see app/main.py's own writeup on the exact mechanism),
    because both reverse proxies in front of this app (frontend/nginx.conf,
    deploy/Caddyfile) strip /api before forwarding, so the app never
    actually receives a path containing it. Asserts the fix directly on
    the app object (root_path must be empty, full stop) rather than only
    on env-dependent behavior, so this can't silently regress if root_path
    is ever reintroduced under a different-looking env var."""

    from app.main import app as fastapi_app

    assert fastapi_app.root_path == ""
    for path in ("/static/audio/cuemix-demo.wav", "/static/audio/GENERATED_AUDIO.md"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} should be reachable without any /api prefix"


def test_cors_origins_are_environment_configurable(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example, https://two.example/")
    assert cors_origins() == ["https://one.example", "https://two.example"]


def test_public_api_urls_follow_deployment_base(monkeypatch):
    monkeypatch.setenv("BACKEND_PUBLIC_URL", "https://api.example.test/v1/")
    assert public_api_url("/uploads/7") == "https://api.example.test/v1/uploads/7"
