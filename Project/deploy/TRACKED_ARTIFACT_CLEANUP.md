# Tracked artifact cleanup

The current revision cleanup is complete:

- The backend virtual environment, root `node_modules`, virtual-environment
  archive, IDE workspace file, Python bytecode, and test caches were removed
  from the Git index without deleting their local working copies.
- The unused, uncleared `backend/app/static/audio/demo.mp3` was deleted from the
  current revision. Runtime fallback audio is the original, reproducibly
  generated `cuemix-demo.wav`.
- Repository and project ignore rules prevent these generated paths from being
  added again. Future MP3 files are assigned to Git LFS.
- `.vscode`, feedback files, and unrelated working files were not included.

No history rewrite was performed. The old MP3 and generated dependencies still
occupy old commits, so existing clones do not immediately shrink. Removing them
from shared history requires a separately reviewed `git filter-repo` migration,
coordination with every contributor, backup verification, and a force-push.
Do not perform that operation as part of ordinary feature work.
