# Cuemix

Cuemix is a SvelteKit + FastAPI + PostgreSQL prototype for prompt-guided DJ
sessions, plus a mix library and social layer built on top of it. It is not a
trained AI DJ: candidate ordering runs on deterministic string similarity,
keyword rules, reciprocal-rank fusion, and BPM/key arithmetic, with one
optional, schema-constrained LLM call (a local Ollama model, the sole LLM
option) used only for prompt classification, never for track selection or
ranking.

The AI-DJ pipeline is `VibeUnderstander -> CandidateRetriever -> SegmentSelector
-> TransitionPlanner -> AudioRenderer`, each stage an interface in
`backend/app/services/pipeline/interfaces.py` with a swappable implementation
bound in `pipeline/dependencies.py`. Candidates come from a local catalog or
Audius; segments are chosen with librosa; transitions are planned
deterministically and rendered with pydub/ffmpeg. Live sessions currently
render one audio segment at a time (the transition planner's output is
explanatory metadata, not an audible crossfade); saved multi-track mixes do
crossfade for real.

## Quick start

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open the app at <http://localhost:8080> and the API docs at
<http://localhost:8080/api/docs>. Compose applies all Alembic migrations
before starting the API and UI. The Ollama container starts by default, but
the model isn't pulled automatically — run
`docker compose exec ollama ollama pull qwen3:8b` once to actually use LLM
prompt classification; `docker-compose.yml`'s local default for
`VIBE_LLM_PROVIDER` is `none`, while `docker-compose.prod.yml` and the app's
own fallback both default to `ollama`.

To add clearly labelled sample forum records to a local demo only, run the
idempotent seed explicitly; application startup never seeds data:

```powershell
docker compose exec -e ALLOW_DEMO_SEED=true backend python -m app.seed
```

## What's implemented

| Area | Status |
| --- | --- |
| Svelte UI, player controls, cookie-auth client | Implemented |
| FastAPI auth (PBKDF2-SHA256), CSRF/origin guard, rate limits | Implemented |
| Persistent sessions, feedback, preferences, personalized prompt-shortcut chips | Implemented, retriever-agnostic |
| AI-DJ pipeline: catalog + Audius retrieval, librosa segment selection, deterministic transition planning | Implemented |
| pydub/ffmpeg audio rendering | Implemented for saved mixes (real crossfades); live sessions render one segment at a time |
| Catalog track upload with async BPM/key/segment analysis | Implemented |
| Fuzzy artist-name catalog search (Postgres pg_trgm, pure-Python fallback) | Implemented |
| Mix library, publishing, likes, saves | Implemented |
| Community: Friends/Explore/Discussions/People, posts/comments/votes, mix sharing, attachments | Implemented |
| Public profiles, mutual friends, friend-only DMs, live/durable notifications, block/report | Implemented |
| Music Identity analytics (listening history, period filters, visibility controls) | Implemented; a "Listening DNA" ML feature is a stable but deliberately unimplemented contract |
| Trained ranking/recommendation model | Deliberately not implemented |
| LLM prompt refinement | Implemented; local Ollama (sole option) or off (`VIBE_LLM_PROVIDER=none`) |
| CI | Every push/PR runs backend tests (80% coverage gate), frontend checks/tests/e2e, and container builds |
| Azure CD | Live at `https://sweng-group-18.eastus.cloudapp.azure.com`; auto-deploys `main` on green CI — see [deploy/README.md](deploy/README.md) |

## Repo layout

- [backend/](backend/README.md) — FastAPI app, AI-DJ pipeline, Alembic migrations, tests.
- [frontend/](frontend/README.md) — SvelteKit UI.
- [deploy/](deploy/README.md) — production Compose stack, backup/restore/rollback, CI/CD operations.
- [SECURITY.md](SECURITY.md) — vulnerability reporting and known exceptions.

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
or unlicensed audio. Runtime demo playback uses an original, procedurally
generated `cuemix-demo.wav` (see [backend/app/static/audio/GENERATED_AUDIO.md](backend/app/static/audio/GENERATED_AUDIO.md))
— no third-party sample.
