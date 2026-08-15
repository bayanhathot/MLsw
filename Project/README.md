# Cuemix

Cuemix is a SvelteKit, FastAPI, and PostgreSQL prototype for prompt-guided DJ
sessions. Session start/feedback and mix generation are routed through one
consolidated, swappable AI-DJ pipeline (`VibeUnderstander` -> deterministic
catalog/Audius `CandidateRetriever` -> librosa `SegmentSelector` ->
deterministic `TransitionPlanner` -> pydub/ffmpeg `AudioRenderer`) — see
[AI_DJ_PIPELINE.md](AI_DJ_PIPELINE.md) for the full write-up. It is not a
trained music model: candidate ordering is deterministic string similarity,
keyword rules, and BPM/key arithmetic throughout, with one optional,
schema-constrained LLM call (a fully local Ollama model, the sole LLM option)
for prompt classification.

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
| Persistent sessions, feedback, and user preferences | Implemented, retriever-agnostic (works against catalog or Audius) |
| Consolidated AI-DJ pipeline: catalog + Audius candidate retrieval, librosa segment selection, deterministic transition planning | Implemented |
| Real pydub/ffmpeg audio rendering and crossfading (mixes + sessions) | Implemented |
| Catalog track upload (album/artist/lyrics + audio) with async BPM/key/segment analysis | Implemented |
| Fuzzy artist-name catalog search (Postgres pg_trgm, pure-Python fallback) | Implemented |
| Mix library/feed, publishing, likes, and saves | Implemented UI/API vertical slice |
| Community: Friends/Explore/Discussions/People, posts/comments/votes, native mix sharing, and attachments | Implemented UI/API vertical slice |
| Social-first public profiles, mutual friends, search/discovery, friend-only DMs, live/durable notifications, block/report | Implemented UI/API vertical slice |
| Music Identity analytics, raw listening events, period filters, and private/friends/public visibility | Implemented full-stack infrastructure; Listening DNA ML intentionally deferred |
| Bounded upload queue and persistent attachment volume | Implemented prototype; queue state is process-local |
| Trained ranking/recommendation model | Deliberately not implemented; see [AI_DJ_PIPELINE.md](AI_DJ_PIPELINE.md) |
| LLM prompt refinement | Implemented; Ollama (local, sole option, `VIBE_LLM_PROVIDER`) or off (`none`) |
| CI | Installed at repository root; the first hosted run is still pending |
| Azure CD | Template only; VM, DNS, secrets, and first deployment are external prerequisites |

The complete architecture, commands, limitations, security notes, and roadmap
are in [CUEMIX_PROJECT_README.md](CUEMIX_PROJECT_README.md). The AI-DJ pipeline
(stages, why each is swappable, deterministic-vs-LLM breakdown, and what's
deferred) is in [AI_DJ_PIPELINE.md](AI_DJ_PIPELINE.md). Music Identity data
flow, privacy, future ML integration points, and a debugging checklist are in
[MUSIC_IDENTITY.md](MUSIC_IDENTITY.md). The V3 social-product architecture and
debugging flow are in [SOCIAL_PRODUCT_V3.md](SOCIAL_PRODUCT_V3.md), with an
implementation summary in [IMPLEMENTATION_REPORT_V3.md](IMPLEMENTATION_REPORT_V3.md).
Deployment prerequisites are in [deploy/README.md](deploy/README.md).
Generated dependencies and caches have been removed from the current Git
index; the cleanup record and optional history-rewrite notes are in
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
reproducibly generated `cuemix-demo.wav`. The old uncleared MP3 is excluded from
the current revision and container builds, but its old blob remains in Git
history until a separately coordinated rewrite; future MP3 staging uses Git LFS.
