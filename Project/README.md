# Zonix

Zonix is a SvelteKit, FastAPI, and PostgreSQL prototype for prompt-guided DJ
sessions. It currently has a working UI/API/database vertical slice; it is not
yet a trained music model or a real audio-transition engine.

## Quick start

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open the app at <http://localhost:8080> and API docs at
<http://localhost:8080/api/docs>. Compose waits for PostgreSQL, applies all Alembic
migrations, and then starts the API and UI.

| Capability | Status |
| --- | --- |
| Svelte UI, player controls, and cookie-auth client | Implemented |
| FastAPI auth, CSRF origin guard, and rate limits | Implemented |
| Persistent sessions, feedback, and user preferences | Implemented |
| Audius mix planning with a controlled local fallback | Implemented prototype |
| Mix library/feed, publishing, likes, and saves | Implemented UI/API vertical slice |
| Forum posts/comments/votes and attachments | Implemented UI/API vertical slice |
| Profiles, direct messages, and live/durable notifications | Implemented UI/API vertical slice |
| Bounded upload queue and persistent attachment volume | Implemented prototype; queue state is process-local |
| Real audio segmentation/crossfading | Not implemented |
| Trained prompt-to-segment model | Not implemented |
| DVC/MLflow evaluation | Runnable scaffold using synthetic data, not model evidence |
| Local LLM | Scaffolded; Ollama model pull and host resources are external prerequisites |
| CI | Installed at repository root; the first hosted run is still pending |
| Azure CD | Template only; VM, DNS, secrets, and first deployment are external prerequisites |

The complete architecture, commands, limitations, security notes, and roadmap
are in [ZONIX_PROJECT_README.md](ZONIX_PROJECT_README.md). The offline baseline
is documented in [ML_PIPELINE.md](ML_PIPELINE.md), and deployment prerequisites
are in [deploy/README.md](deploy/README.md). Generated dependencies and caches
have been removed from the current Git index; the cleanup record and optional
history-rewrite notes are in
[deploy/TRACKED_ARTIFACT_CLEANUP.md](deploy/TRACKED_ARTIFACT_CLEANUP.md).

To add clearly labelled sample forum records to a local demo only, run the
idempotent seed explicitly; application startup never seeds data:

```powershell
docker compose exec -e ALLOW_DEMO_SEED=true backend python -m app.seed
```

## Required checks

```powershell
cd backend
python -m pip install --requirement requirements-dev.txt
python -m alembic upgrade head
python -m alembic check
pytest --cov=app --cov-report=term-missing --cov-fail-under=80

cd ../frontend
npm ci
npm run check
npm test
npm run lint
npm audit --audit-level=moderate
npm run build
npx playwright install chromium # first run on a developer machine
npm run test:e2e
```

Do not commit `.env`, virtual environments, `node_modules`, model downloads,
DVC/MLflow caches, or unlicensed audio. Runtime demo playback uses the original,
reproducibly generated `zonix-demo.wav`. The old uncleared MP3 is excluded from
the current revision and container builds, but its old blob remains in Git
history until a separately coordinated rewrite; future MP3 staging uses Git LFS.
