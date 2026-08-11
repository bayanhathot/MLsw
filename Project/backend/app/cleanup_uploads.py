"""Find or delete media files that have no Attachment database row.

The command is dry-run by default. Deletion must run while the API is stopped,
because in-process upload jobs have not created Attachment rows yet::

    python -m app.cleanup_uploads --delete --confirm-backend-stopped
"""

import argparse
import os

from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.database.models.attachment import Attachment
from app.services.upload_queue import UPLOAD_DIR


def cleanup_orphans(db: Session, delete: bool = False) -> list[str]:
    root = UPLOAD_DIR.resolve()
    if not root.exists():
        return []
    referenced = {row[0] for row in db.query(Attachment.storage_name).all()}
    orphans = []
    for path in root.iterdir():
        resolved = path.resolve()
        if not path.is_file() or path.name == ".gitkeep" or resolved.parent != root:
            continue
        if path.name not in referenced:
            orphans.append(path.name)
            if delete:
                path.unlink(missing_ok=True)
    return sorted(orphans)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="delete the reported orphan files")
    parser.add_argument(
        "--confirm-backend-stopped",
        action="store_true",
        help="confirm no API process can have an active, unmaterialized upload",
    )
    args = parser.parse_args()
    delete = args.delete or os.getenv("DELETE_ORPHAN_UPLOADS", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    confirmed_stopped = args.confirm_backend_stopped or os.getenv(
        "CONFIRM_BACKEND_STOPPED", "false"
    ).lower() in {"1", "true", "yes"}
    if delete and not confirmed_stopped:
        raise SystemExit(
            "Refusing deletion while active uploads may exist; stop the backend and pass "
            "--confirm-backend-stopped."
        )
    with SessionLocal() as db:
        orphans = cleanup_orphans(db, delete=delete)
    action = "deleted" if delete else "found (dry run)"
    print(f"{len(orphans)} orphan upload(s) {action}: {orphans}")


if __name__ == "__main__":
    main()
