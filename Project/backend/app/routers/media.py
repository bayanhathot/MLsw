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
