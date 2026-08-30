"""Public serving for AudioRenderer's rendered composite mix audio.

A plain route rather than a StaticFiles mount: UPLOAD_DIR is resolved from
an environment variable that tests monkeypatch per-run, and a StaticFiles
mount would freeze that directory at app-import time instead of per-request.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services import upload_queue as uq

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/renders/{filename}")
def serve_rendered_audio(filename: str):
    root = (uq.UPLOAD_DIR / "renders").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Rendered audio not found.")
    return FileResponse(
        path,
        media_type="audio/wav",
        content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


# Durable counterpart to serve_rendered_audio above -- serves a published
# 'rendered_asset' mix's composite audio out of the subdirectory
# audio_renderer.promote_render_to_published() copies it into, which the
# temporary-render TTL sweep never scans (see that function's own
# docstring). A distinct route, not a query flag on the one above: the two
# directories have different lifetime/durability guarantees and must never
# be reachable through the same path-traversal-checked root.
@router.get("/renders/published/{filename}")
def serve_published_rendered_audio(filename: str):
    root = (uq.UPLOAD_DIR / "renders" / "published").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Rendered audio not found.")
    return FileResponse(
        path,
        media_type="audio/wav",
        content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
