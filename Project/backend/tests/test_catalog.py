import time
from pathlib import Path

from conftest import register_and_login

from app.database.models.catalog import CatalogTrack

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
).read_bytes()


def _upload(client, **overrides):
    fields = {"album": "Test Album", "artist": "The Testers", "lyrics": "la la la"}
    fields.update(overrides)
    return client.post(
        "/catalog/tracks",
        data=fields,
        files={"file": ("track.wav", _DEMO_WAV_BYTES, "audio/wav")},
    )


def _wait_for_analysis(db_session, track_id, timeout=60.0):
    # librosa's numba-jitted beat tracker JIT-compiles on first use, which
    # can take a while cold (especially under full-suite CPU contention in
    # CI); later calls are fast.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db_session.expire_all()
        row = db_session.query(CatalogTrack).filter_by(id=track_id).first()
        if row.analysis_status in ("completed", "failed"):
            return row
        time.sleep(0.02)
    return row


def test_upload_requires_album_and_artist_but_not_lyrics(client):
    # Lyrics are optional by design (instrumental tracks are first-class,
    # see ai-dj-segment-metadata-architecture.md §3) -- album/artist stay
    # required for display/fuzzy-search/dedup.
    register_and_login(client)
    assert _upload(client, album="").status_code == 422
    assert _upload(client, artist="   ").status_code == 422
    response = _upload(client, lyrics="")
    assert response.status_code == 201, response.text
    assert response.json()["lyrics"] is None


def test_upload_rejects_signature_mismatch(client):
    register_and_login(client)
    response = client.post(
        "/catalog/tracks",
        data={"album": "A", "artist": "B", "lyrics": "C"},
        files={"file": ("fake.wav", b"not really a wav file", "audio/wav")},
    )
    assert response.status_code == 422
    assert "signature" in response.json()["detail"].lower()


def test_upload_stores_track_runs_analysis_and_is_playable(client, db_session):
    register_and_login(client)
    response = _upload(client, title="My Song", genre="lofi")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "My Song"
    assert body["artist"] == "The Testers"
    assert body["album"] == "Test Album"
    assert body["genre"] == "lofi"
    assert body["duration_seconds"] > 0
    assert body["analysis_status"] in ("pending", "completed")
    assert body["audio_url"].endswith(f"/catalog/tracks/{body['id']}/audio")

    served = client.get(body["audio_url"].removeprefix("/api"))
    assert served.status_code == 200
    assert served.content == _DEMO_WAV_BYTES

    row = _wait_for_analysis(db_session, body["id"])
    assert row.analysis_status == "completed"
    assert row.bpm is not None
    assert row.musical_key is not None
    assert row.segment_start_second is not None
    assert row.segment_end_second > row.segment_start_second


def test_upload_defaults_to_private_visibility_and_persists_the_checksum(client, db_session):
    register_and_login(client)
    body = _upload(client, title="Quiet Track").json()
    assert body["visibility"] == "private"

    row = db_session.query(CatalogTrack).filter_by(id=body["id"]).first()
    assert row.visibility == "private"
    assert row.checksum_sha256 is not None
    assert len(row.checksum_sha256) == 64  # hex-encoded SHA-256


def test_upload_can_be_marked_public(client):
    register_and_login(client)
    body = _upload(client, title="Loud Track", visibility="public").json()
    assert body["visibility"] == "public"


def test_upload_rejects_an_invalid_visibility_value(client):
    register_and_login(client)
    response = _upload(client, visibility="friends")
    assert response.status_code == 422


def test_lossless_audio_gets_a_much_higher_size_cap_than_the_old_flat_10mib(client):
    # A perfectly ordinary few-minute WAV routinely exceeds 10 MiB -- this
    # file is comfortably over that old flat cap but under the new
    # format-specific lossless one (CATALOG_AUDIO_MAX_MB_LOSSLESS, 100 MiB
    # default). Not real decodable audio -- only the RIFF/WAVE signature
    # matters for validate_upload; duration probing fails open to 0.
    register_and_login(client)
    big_wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * (11 * 1024 * 1024)
    response = client.post(
        "/catalog/tracks",
        data={"album": "Test Album", "artist": "The Testers"},
        files={"file": ("big.wav", big_wav, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["duration_seconds"] == 0


def test_compressed_audio_keeps_a_lower_size_cap_than_lossless(client):
    register_and_login(client)
    too_big_mp3 = b"ID3" + b"\x00" * (31 * 1024 * 1024)
    response = client.post(
        "/catalog/tracks",
        data={"album": "Test Album", "artist": "The Testers"},
        files={"file": ("big.mp3", too_big_mp3, "audio/mpeg")},
    )
    assert response.status_code == 413


def test_uploaded_artist_resolves_via_fuzzy_catalog_search(client, db_session):
    register_and_login(client)
    upload = _upload(client, artist="Nova Blackwood", title="Skyline").json()
    _wait_for_analysis(db_session, upload["id"])

    session = client.post(
        "/sessions/start", json={"prompt": "play something by nova blackwood"}
    )
    assert session.status_code == 200
    assert session.json()["nowPlaying"]["artist"] == "Nova Blackwood"
    assert session.json()["nowPlaying"]["title"] == "Skyline"
