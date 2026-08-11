from app.cleanup_uploads import cleanup_orphans


def test_orphan_cleanup_is_dry_run_then_controlled_delete(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.cleanup_uploads.UPLOAD_DIR", tmp_path)
    orphan = tmp_path / "orphan.mp3"
    orphan.write_bytes(b"ID3x")
    assert cleanup_orphans(db_session) == ["orphan.mp3"]
    assert orphan.exists()
    assert cleanup_orphans(db_session, delete=True) == ["orphan.mp3"]
    assert not orphan.exists()
