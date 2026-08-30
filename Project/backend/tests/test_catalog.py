import hashlib
import io
import time
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import register_and_login

from app.database.models.catalog import CatalogTrack
from app.main import app
from app.services.audio_analysis import camelot_for


def anonymous():
    """A fresh, never-logged-in TestClient against the same app instance."""

    return TestClient(app)

_DEMO_WAV_BYTES = (
    Path(__file__).resolve().parents[1] / "app" / "static" / "audio" / "cuemix-demo.wav"
).read_bytes()


def _upload(client, **overrides):
    fields = {"title": "Test Track", "album": "Test Album", "artist": "The Testers", "lyrics": "la la la"}
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


def test_upload_requires_title_album_and_artist_but_not_lyrics(client):
    # Lyrics are optional by design (instrumental tracks are first-class,
    # see ai-dj-segment-metadata-architecture.md §3) -- title/album/artist
    # stay required for display/fuzzy-search/dedup. The old filename-stem
    # title fallback is gone: an upload with no title is rejected, not
    # silently titled after its filename.
    register_and_login(client)
    assert _upload(client, title="").status_code == 422
    assert _upload(client, album="").status_code == 422
    assert _upload(client, artist="   ").status_code == 422
    response = _upload(client, lyrics="")
    assert response.status_code == 201, response.text
    assert response.json()["lyrics"] is None

    # Distinct from the blank-string case above: the lyrics *field itself*
    # never present in the multipart body at all, matching what a real
    # instrumental-track upload sends when the UI's lyrics textarea is left
    # untouched and never appended to FormData.
    omitted = client.post(
        "/catalog/tracks",
        data={"title": "No Lyrics Field", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("track.wav", _DEMO_WAV_BYTES, "audio/wav")},
    )
    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["lyrics"] is None


def test_upload_rejects_signature_mismatch(client):
    register_and_login(client)
    response = client.post(
        "/catalog/tracks",
        data={"title": "Fake", "album": "A", "artist": "B", "lyrics": "C"},
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
    # Lets future targeted reprocessing (e.g. "everything below version N",
    # "everything analyzed before date X") query these independently --
    # see CatalogTrack.analysis_version's own docstring. "v4": v3 plus a
    # low-sample-rate chroma fallback; v3 already included the absolute
    # segment-level floor and real Krumhansl-Schmuckler key-finding.
    assert row.analysis_version == "v4"
    assert row.analyzed_at is not None
    # Genuine confidence signals read off the same librosa computations
    # bpm/musical_key are chosen from (see audio_analysis._bpm_confidence/
    # _estimate_key), not placeholders -- both normalized to [0.0, 1.0].
    assert row.bpm_confidence is not None
    assert 0.0 <= row.bpm_confidence <= 1.0
    assert row.key_confidence is not None
    assert 0.0 <= row.key_confidence <= 1.0
    # Real key-finding now also picks a mode, and camelot is a
    # deterministic lookup from (musical_key, key_mode) -- see
    # audio_analysis.camelot_for.
    assert row.key_mode in ("major", "minor")
    assert row.camelot is not None
    assert row.camelot == camelot_for(row.musical_key, row.key_mode)
    # ITU-R BS.1770 integrated loudness (pyloudnorm) -- always negative in
    # practice, well above the -70 LUFS absolute silence gate.
    assert row.integrated_loudness_lufs is not None
    assert -70.0 < row.integrated_loudness_lufs < 0.0
    # Beat-grid timing, reused from beat_track's own beat-frame output (see
    # audio_analysis._beat_grids) -- the 60s demo wav has real beats.
    assert row.beat_grid_json
    assert all(isinstance(t, (int, float)) for t in row.beat_grid_json)
    assert row.beat_grid_json == sorted(row.beat_grid_json)
    # downbeat_grid/phrase_boundaries are the declared coarse 4/4 + 8-bar
    # heuristic -- exact fixed-stride slices of beat_grid_json.
    assert row.downbeat_grid_json == row.beat_grid_json[::4]
    assert row.phrase_boundaries_json == row.downbeat_grid_json[::8]


def test_duplicate_upload_reuses_storage_and_analysis_without_recomputing(client, db_session, monkeypatch):
    # Same bytes, same metadata: the second upload must reuse the first's
    # already-computed analysis and physical file rather than re-running
    # analyze_catalog_track (a real, non-trivial librosa job) a second time
    # for content already proven identical.
    import app.services.upload_queue as uq_module

    register_and_login(client)
    first = _upload(client, title="Same Song", artist="Same Artist", album="Same Album")
    assert first.status_code == 201, first.text
    first_row = _wait_for_analysis(db_session, first.json()["id"])
    assert first_row.analysis_status == "completed"
    assert first_row.bpm is not None
    assert first_row.checksum_sha256 is not None

    analysis_calls = []
    original_submit_analysis = uq_module.upload_queue.submit_analysis

    def counting_submit_analysis(*args, **kwargs):
        analysis_calls.append((args, kwargs))
        return original_submit_analysis(*args, **kwargs)

    monkeypatch.setattr(uq_module.upload_queue, "submit_analysis", counting_submit_analysis)

    second = _upload(client, title="Same Song", artist="Same Artist", album="Same Album")
    assert second.status_code == 201, second.text
    second_body = second.json()

    assert analysis_calls == []  # no new analysis was ever dispatched
    assert second_body["id"] != first_row.id
    assert second_body["analysis_status"] == "completed"  # populated immediately, never "pending"

    second_row = db_session.query(CatalogTrack).filter_by(id=second_body["id"]).first()
    assert second_row.checksum_sha256 == first_row.checksum_sha256
    assert second_row.bpm == first_row.bpm
    assert second_row.musical_key == first_row.musical_key
    assert second_row.key_mode == first_row.key_mode
    assert second_row.camelot == first_row.camelot
    assert second_row.beat_grid_json == first_row.beat_grid_json
    assert second_row.downbeat_grid_json == first_row.downbeat_grid_json
    assert second_row.phrase_boundaries_json == first_row.phrase_boundaries_json
    assert second_row.segment_start_second == first_row.segment_start_second
    assert second_row.segment_end_second == first_row.segment_end_second
    assert second_row.storage_name == first_row.storage_name  # reused physical file
    assert second_row.analysis_version == first_row.analysis_version
    assert second_row.analyzed_at == first_row.analyzed_at
    assert second_row.bpm_confidence == first_row.bpm_confidence
    assert second_row.key_confidence == first_row.key_confidence
    assert second_row.integrated_loudness_lufs == first_row.integrated_loudness_lufs


def test_duplicate_of_failed_analysis_is_reanalyzed_instead_of_copying_failure(client, db_session):
    """Regression: a failed checksum match used to be treated as reusable,
    so every later upload of those valid bytes immediately inherited
    ``failed`` and could never benefit from an analyzer fix."""

    register_and_login(client)
    failed_row = CatalogTrack(
        title="Old failed analysis",
        artist="Test Artist",
        album="Test Album",
        storage_name="old-failed.wav",
        content_type="audio/wav",
        duration_seconds=60,
        analysis_status="failed",
        checksum_sha256=hashlib.sha256(_DEMO_WAV_BYTES).hexdigest(),
    )
    db_session.add(failed_row)
    db_session.commit()

    response = _upload(client, title="Retry after analyzer fix")
    assert response.status_code == 201, response.text
    assert response.json()["analysis_status"] == "pending"

    retried = _wait_for_analysis(db_session, response.json()["id"])
    assert retried.analysis_status == "completed"
    assert retried.storage_name != failed_row.storage_name
    assert retried.analysis_version == "v4"


def test_duplicate_upload_with_different_metadata_still_creates_its_own_row(client, db_session):
    # Same audio, but a different title/artist -- a legitimate remix or a
    # different official release sharing the same master must still get
    # its own catalog row, never merged or rejected just because the bytes
    # already exist.
    register_and_login(client)
    original = _upload(client, title="Original Mix", artist="Artist A", album="Album A")
    assert original.status_code == 201, original.text
    original_row = _wait_for_analysis(db_session, original.json()["id"])
    assert original_row.analysis_status == "completed"

    remix = _upload(client, title="Remix Version", artist="Artist B", album="Album B")
    assert remix.status_code == 201, remix.text
    remix_body = remix.json()

    assert remix_body["id"] != original_row.id
    assert remix_body["title"] == "Remix Version"
    assert remix_body["artist"] == "Artist B"
    assert remix_body["album"] == "Album B"
    assert remix_body["analysis_status"] == "completed"

    remix_row = db_session.query(CatalogTrack).filter_by(id=remix_body["id"]).first()
    assert remix_row.checksum_sha256 == original_row.checksum_sha256
    assert remix_row.bpm == original_row.bpm
    assert remix_row.musical_key == original_row.musical_key
    assert remix_row.storage_name == original_row.storage_name


def test_single_upload_survives_the_unclaimed_file_ttl_prune(client):
    # The single-file endpoint's underlying upload_queue job must be marked
    # "claimed" (set_catalog_track) the moment the CatalogTrack row exists --
    # otherwise UploadQueue._prune()'s unclaimed-file TTL cleanup (built for
    # a generic attachment nobody ever attached to a post) would eventually
    # delete this track's audio file right out from under its still-live
    # CatalogTrack row.
    import app.services.upload_queue as uq

    register_and_login(client)
    body = _upload(client, title="Survives Prune").json()

    original_ttl = uq.upload_queue._unclaimed_ttl
    uq.upload_queue._unclaimed_ttl = 0
    try:
        uq.upload_queue._prune()
    finally:
        uq.upload_queue._unclaimed_ttl = original_ttl

    served = client.get(body["audio_url"].removeprefix("/api"))
    assert served.status_code == 200


def test_upload_defaults_to_public_visibility_and_persists_the_checksum(client, db_session):
    register_and_login(client)
    body = _upload(client, title="Quiet Track").json()
    assert body["visibility"] == "public"

    row = db_session.query(CatalogTrack).filter_by(id=body["id"]).first()
    assert row.visibility == "public"
    assert row.checksum_sha256 is not None
    assert len(row.checksum_sha256) == 64  # hex-encoded SHA-256


def test_upload_can_be_marked_private(client):
    register_and_login(client)
    body = _upload(client, title="Quiet Track", visibility="private").json()
    assert body["visibility"] == "private"


def test_upload_rejects_an_invalid_visibility_value(client):
    register_and_login(client)
    response = _upload(client, visibility="friends")
    assert response.status_code == 422


def test_lossless_audio_gets_a_much_higher_size_cap_than_the_old_flat_10mib(client):
    # A perfectly ordinary few-minute WAV routinely exceeds 10 MiB -- this
    # file is comfortably over that old flat cap but under the new
    # format-specific lossless one (CATALOG_AUDIO_MAX_MB_LOSSLESS, 100 MiB
    # default). Looping the real demo clip (rather than a zero-filled
    # RIFF/WAVE header) keeps it genuinely decodable and non-silent, since
    # requirement 5's deep validation now rejects anything that isn't.
    from pydub import AudioSegment

    register_and_login(client)
    demo = AudioSegment.from_file(io.BytesIO(_DEMO_WAV_BYTES), format="wav")
    buf = io.BytesIO()
    (demo * 5).export(buf, format="wav")  # ~13 MiB, well over the old 10 MiB cap
    big_wav = buf.getvalue()
    assert len(big_wav) > 11 * 1024 * 1024

    response = client.post(
        "/catalog/tracks",
        data={"title": "Big Track", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("big.wav", big_wav, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["duration_seconds"] >= 290


def test_compressed_audio_keeps_a_lower_size_cap_than_lossless(client):
    register_and_login(client)
    too_big_mp3 = b"ID3" + b"\x00" * (31 * 1024 * 1024)
    response = client.post(
        "/catalog/tracks",
        data={"title": "Too Big", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("big.mp3", too_big_mp3, "audio/mpeg")},
    )
    assert response.status_code == 413


def test_upload_rejects_corrupt_undecodable_audio(client):
    # Signature-valid (RIFF/WAVE header) but not actually decodable --
    # requirement 5's deep validation, not just the cheap byte-signature
    # check, is what has to reject this.
    register_and_login(client)
    corrupt_wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 200
    response = client.post(
        "/catalog/tracks",
        data={"title": "Corrupt", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("corrupt.wav", corrupt_wav, "audio/wav")},
    )
    assert response.status_code == 422, response.text
    assert "decode" in response.json()["detail"].lower()


def test_upload_rejects_silent_audio(client):
    from pydub import AudioSegment

    register_and_login(client)
    buf = io.BytesIO()
    AudioSegment.silent(duration=2000, frame_rate=22050).export(buf, format="wav")
    response = client.post(
        "/catalog/tracks",
        data={"title": "Silence", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("silence.wav", buf.getvalue(), "audio/wav")},
    )
    assert response.status_code == 422, response.text
    assert "silent" in response.json()["detail"].lower()


def test_upload_rejects_near_silent_low_level_noise_audio(client):
    # A real near-silent file (dither noise, a muted room, a bad export)
    # has rms > 0 and slipped straight through the old `segment.rms == 0`
    # check -- this is the regression guard for that gap. Built from real
    # numpy noise, not synthetic zeros, scaled to roughly -60 dBFS (well
    # under _SILENT_UPLOAD_FLOOR_DBFS's -50 floor), exported to a real wav.
    import numpy as np
    from pydub import AudioSegment

    register_and_login(client)
    sr = 22050
    duration_seconds = 2.0
    rng = np.random.default_rng(seed=0)
    noise = rng.normal(0.0, 1.0, int(sr * duration_seconds))
    # Scale so RMS amplitude sits at roughly -60 dBFS relative to 16-bit
    # full scale (32767): target_rms = 32767 * 10**(-60/20).
    target_rms = 32767 * (10 ** (-60 / 20))
    scaled = noise / (np.sqrt(np.mean(noise**2)) + 1e-9) * target_rms
    samples = np.clip(scaled, -32768, 32767).astype(np.int16)
    segment = AudioSegment(
        samples.tobytes(), frame_rate=sr, sample_width=2, channels=1
    )
    assert segment.dBFS < -50, f"test fixture isn't actually near-silent: {segment.dBFS} dBFS"

    buf = io.BytesIO()
    segment.export(buf, format="wav")
    response = client.post(
        "/catalog/tracks",
        data={"title": "Near Silent Noise", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("near_silent.wav", buf.getvalue(), "audio/wav")},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"].lower()
    # Same class of rejection as true silence (silent/too quiet), not a
    # different, unrelated error (e.g. a decode failure).
    assert "silent" in detail or "quiet" in detail


def test_upload_rejects_an_unsupported_audio_format(client):
    register_and_login(client)
    response = client.post(
        "/catalog/tracks",
        data={"title": "Unsupported", "album": "Test Album", "artist": "The Testers"},
        files={"file": ("clip.aac", b"whatever bytes", "audio/aac")},
    )
    assert response.status_code == 415


def test_owner_can_stream_their_own_private_track(client):
    register_and_login(client, "alice", "alice@example.com")
    body = _upload(client, title="Alice's Track", visibility="private").json()
    assert body["visibility"] == "private"
    served = client.get(f"/catalog/tracks/{body['id']}/audio")
    assert served.status_code == 200


def test_another_user_cannot_stream_a_private_track(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    body = _upload(client, title="Alice's Track", visibility="private").json()
    served = second_client.get(f"/catalog/tracks/{body['id']}/audio")
    assert served.status_code == 404


def test_anonymous_cannot_stream_any_catalog_audio(client):
    register_and_login(client, "alice", "alice@example.com")
    body = _upload(client, title="Alice's Track", visibility="public").json()
    anon = anonymous()
    served = anon.get(f"/catalog/tracks/{body['id']}/audio")
    assert served.status_code == 401


def test_another_user_can_stream_a_public_track(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    body = _upload(client, title="Alice's Track", visibility="public").json()
    served = second_client.get(f"/catalog/tracks/{body['id']}/audio")
    assert served.status_code == 200


_COVER_JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # minimal, real JPEG signature


def test_upload_without_a_cover_has_no_cover_url(client):
    register_and_login(client)
    body = _upload(client, title="No Cover").json()
    assert body["cover_url"] is None


def test_upload_with_a_cover_stores_and_serves_it(client):
    register_and_login(client)
    response = client.post(
        "/catalog/tracks",
        data={"title": "With Cover", "album": "Test Album", "artist": "The Testers"},
        files={
            "file": ("track.wav", _DEMO_WAV_BYTES, "audio/wav"),
            "cover": ("cover.jpg", _COVER_JPG_BYTES, "image/jpeg"),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["cover_url"] is not None
    assert body["cover_url"].endswith(f"/catalog/tracks/{body['id']}/cover")

    served = client.get(body["cover_url"].removeprefix("/api"))
    assert served.status_code == 200
    assert served.content == _COVER_JPG_BYTES


def test_cover_art_rejects_an_invalid_image(client):
    register_and_login(client)
    response = client.post(
        "/catalog/tracks",
        data={"title": "Bad Cover", "album": "Test Album", "artist": "The Testers"},
        files={
            "file": ("track.wav", _DEMO_WAV_BYTES, "audio/wav"),
            "cover": ("cover.jpg", b"not really a jpeg", "image/jpeg"),
        },
    )
    assert response.status_code == 422
    assert "cover art" in response.json()["detail"].lower()


def test_cover_art_is_hidden_from_a_private_tracks_non_owner(client, second_client):
    register_and_login(client, "alice", "alice@example.com")
    register_and_login(second_client, "bob", "bob@example.com")
    body = client.post(
        "/catalog/tracks",
        data={"title": "Alice's Cover", "album": "A", "artist": "B", "visibility": "private"},
        files={
            "file": ("track.wav", _DEMO_WAV_BYTES, "audio/wav"),
            "cover": ("cover.jpg", _COVER_JPG_BYTES, "image/jpeg"),
        },
    ).json()
    cover_path = body["cover_url"].removeprefix("/api")
    assert client.get(cover_path).status_code == 200
    assert second_client.get(cover_path).status_code == 404


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
