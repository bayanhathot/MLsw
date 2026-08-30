# CueMix

> University software-engineering project: a full-stack, prompt-guided DJ,
> music Studio, library, and social application that runs locally or on an
> Azure VM without a hosted AI API.

Cuemix is a SvelteKit + FastAPI + PostgreSQL prototype for prompt-guided DJ
sessions, plus a mix library and social layer built on top of it. It is not a
trained AI DJ: candidate ordering runs on deterministic string similarity,
keyword rules, reciprocal-rank fusion, and BPM/key arithmetic. Within the main
DJ pipeline, one optional schema-constrained call to the local Ollama model
refines prompt classification but never performs track selection or ranking.
Studio has a separate, more capable planning assistant described below.

The AI-DJ pipeline is `VibeUnderstander -> CandidateRetriever -> SegmentSelector
-> TransitionPlanner -> AudioRenderer`, each stage an interface in
`backend/app/services/pipeline/interfaces.py` with a swappable implementation
bound in `pipeline/dependencies.py`. Candidates come from a local catalog or
Audius; segments are chosen with librosa; transitions are planned
deterministically and rendered with pydub/ffmpeg. Live sessions currently
render one audio segment at a time (the transition planner's output is
explanatory metadata, not an audible crossfade); saved multi-track mixes do
crossfade for real.

## Contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [What's implemented](#whats-implemented)
- [CueMix Studio](#cuemix-studio)
- [Repository layout](#repository-layout)
- [Development without the full stack](#development-without-the-full-stack)
- [Configuration](#configuration)
- [Testing](#testing)
- [CI/CD and production](#cicd-and-production)
- [Operations](#operations)
- [Security and data handling](#security-and-data-handling)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)

## Architecture

```mermaid
flowchart LR
    Browser[Browser] --> Proxy[Frontend Nginx / production Caddy]
    Proxy --> UI[SvelteKit static app]
    Proxy --> API[FastAPI backend]
    API --> DB[(PostgreSQL)]
    API --> Cache[(Redis)]
    API --> Files[(Upload volume)]
    API --> Audius[Audius Discovery API]
    Browser -->|provider-manifest playback| Audius
    API --> StudioAI[Studio AI service]
    API --> Ollama[Ollama / qwen3:8b]
    StudioAI --> Cache
    StudioAI --> Ollama
```

| Component | Responsibility |
| --- | --- |
| `frontend/` | Svelte 5/SvelteKit interface, global player, Studio waveform editor, community, profiles, and API client |
| `backend/` | FastAPI API, authorization, persistence, DJ pipeline, audio analysis/rendering, upload workers, WebSockets, and validation |
| `studio-ai-service/` | Internal, stateless Studio conversation/planning service; it has no database access |
| PostgreSQL | Durable users, sessions, mixes, Studio drafts, social data, analysis metadata, and migration state |
| Redis | Cross-process real-time fan-out, durable upload-job state, rate/concurrency coordination, and Ollama admission control |
| Ollama | Local `qwen3:8b` inference for prompt refinement and the Studio assistant |
| Nginx/Caddy | Serves the frontend and proxies `/api` to FastAPI; Caddy also terminates production HTTPS |

The browser never calls PostgreSQL, Ollama, or the internal Studio AI service
directly. It talks to FastAPI through `/api`; the backend resolves ownership
and current database state before sending a bounded context to the assistant,
and validates every returned plan again before it can be applied.

## Quick start

### Prerequisites

- Docker Desktop with Docker Compose v2. On Windows, enable the WSL 2 engine.
- Git.
- Enough free disk and memory for the containers and the local model. The
  first `qwen3:8b` download is several gigabytes and Ollama intentionally keeps
  it resident after use for low-latency responses.

All commands in this document assume the current directory is `Project/`, the
directory containing `docker-compose.yml`.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Ubuntu/WSL or Linux:

```bash
cp .env.example .env
docker compose up --build
```

Open the app at <http://localhost:8080> and the API docs at
<http://localhost:8080/api/docs>. Compose applies all Alembic migrations
before starting the API and UI. On the first startup, the one-shot
`ollama-model-init` service automatically downloads and warms `qwen3:8b`, then
the backend and Studio AI start with local LLM support enabled. The model is
kept in the persistent `ollama_data` volume, so later builds and starts reuse
it without another full download. No manual `ollama pull` command is needed.

Compose seeds a realistic ~50-listener dataset -- accounts, profiles, a
social graph, forum posts/comments/votes, direct messages, mixes, DJ
sessions, and listening history (`backend/app/coldseed/build.py`) -- automatically
as part of the one-shot `migrate` service, right after Alembic runs, so the
app always launches looking like it's had real users for months, not empty.
It's idempotent -- re-running it on every `docker compose up` / redeploy
never creates duplicates (a `ColdSeedRun` version marker short-circuits any
run whose `COLD_SEED_VERSION` has already been generated) -- so it's safe to
leave on; set `ENABLE_COLD_SEED=false` to opt out. `COLD_SEED_RANDOM_SEED`
fixes the dataset's RNG, so the same version always reproduces the exact
same data. To re-run it manually against a running deployment (e.g. after
opting out at deploy time, or after bumping `COLD_SEED_VERSION`):

```powershell
docker compose exec -e ENABLE_COLD_SEED=true backend python -m app.seed
```

### Local addresses

| Service | Address |
| --- | --- |
| Application | <http://localhost:8080> |
| API documentation through the frontend proxy | <http://localhost:8080/api/docs> |
| Backend API directly | <http://localhost:5000/docs> |
| Adminer, when the tools profile is enabled | <http://localhost:8081> |

Start Adminer only when it is needed:

```powershell
docker compose --profile tools up -d adminer
```

### Common local commands

```powershell
# Start or resume the stack in the background
docker compose up -d

# Rebuild changed images and start the stack
docker compose up -d --build

# Show service health and state
docker compose ps

# Follow application logs
docker compose logs -f backend frontend studio-ai-service

# Stop the stack while keeping database, uploads, Redis, and model data
docker compose down
```

`docker compose down -v` also deletes all named volumes. That permanently
removes the local database, uploaded files, Redis state, and downloaded Ollama
model, so use it only when a complete reset is intended.

## What's implemented

| Area | Status |
| --- | --- |
| Svelte UI, player controls, cookie-auth client | Implemented |
| FastAPI auth (PBKDF2-SHA256), CSRF/origin guard, rate limits | Implemented |
| Persistent sessions, segment/full-song mixing scope, feedback, preferences, personalized prompt-shortcut chips | Implemented, retriever-agnostic |
| AI-DJ pipeline: catalog + Audius retrieval, librosa segment selection, deterministic transition planning | Implemented |
| pydub/ffmpeg audio rendering | Implemented for saved mixes (real crossfades); live sessions render one segment at a time |
| Catalog track upload with async BPM/key/segment analysis | Implemented |
| Fuzzy artist-name catalog search (Postgres pg_trgm, pure-Python fallback) | Implemented |
| Mix library, rendered-asset/provider-manifest publishing, likes, saves | Implemented |
| CueMix Studio: waveform-assisted exact saved moments, manual timeline, transition preview, render/publish, saved-segment auto-mix | Implemented locally |
| Studio AI assistant | Implemented as an isolated, internal, fail-open service sharing Ollama + Redis; grounded discovery, add/remove/reorder/edit plans, suggested actions, and scope refusals all remain user-controlled |
| Community: Friends/Explore/Discussions/People, posts/comments/votes, mix sharing, attachments | Implemented |
| Public profiles, mutual friends, friend-only DMs, live/durable notifications, block/report | Implemented |
| Music Identity analytics (listening statistics, most-replayed segment, average segment length, time saved, period filters, visibility controls) | Implemented; a "Listening DNA" ML feature is a stable but deliberately unimplemented contract |
| Trained ranking/recommendation model | Deliberately not implemented |
| LLM prompt refinement | Implemented; local Ollama (sole option) or off (`VIBE_LLM_PROVIDER=none`). A verified Azure run on 2026-08-15 admitted at most 4 of 20 concurrent callers with no failures, and passed the included multi-turn reasoning evaluation. |
| CI | Every push/PR runs backend tests (80% coverage gate), frontend checks/tests/e2e, and container builds |
| Azure CD | Live at <https://sweng-group-18.eastus.cloudapp.azure.com>; automatically deploys `main` after all required CI gates pass |

### Main pages

| Route | Purpose |
| --- | --- |
| `/` | Write a prompt, choose segment or full-song mixing, optionally choose an auto-mix mood, and start or change the live AI-DJ session |
| `/feed` | Discover published mixes |
| `/library` | View owned, saved, and published mixes |
| `/studio` | Save exact moments, build and render draft mixes, and use the AI Mix Assistant |
| `/upload` | Add catalog audio for asynchronous analysis |
| `/community` | Friends, Explore, Discussions, and People surfaces |
| `/messages` | Friend-only direct conversations |
| `/users/[username]` | Public profile, statistics, mixes, friends, and permitted Music Identity data |
| `/profile` | Edit the signed-in user's profile, privacy, preferences, and Music Identity view |
| `/admin/debug` | Course/debug visibility when `DEBUG_DASHBOARD_ENABLED=true`; authentication is still required |
| `/login`, `/register` | Cookie-authentication entry points |

`/forum` and `/social` are compatibility redirects to `/community`.

### AI behavior and boundaries

CueMix has two uses of the same local Ollama model, with deliberately different
responsibilities:

1. **Main-page prompt refinement.** A deterministic parser always extracts the
   requested vibe. When enabled, Ollama may refine that structured parse, but
   it does not choose or rank tracks. Auto-mix mood choices are sent as separate
   mode metadata and influence interpretation without replacing the text the
   user wrote with a canned prompt. Segment/full-song scope is also explicit
   request metadata rather than prompt replacement. If Ollama is unavailable
   or times out, the deterministic parse is used.
2. **Studio AI assistant.** The assistant receives the recent conversation plus
   server-built facts about the active mix, active saved segment, listener
   summary, and—only when discovery mode is enabled—real catalog/Audius search
   results. It can explain, clarify conflicting constraints, refuse unrelated
   requests, identify a weak transition, recommend verified discovery results,
   or propose a validated plan. One plan may reorder the remaining mix, change
   up to five outgoing transitions, change one active segment's bounds, remove
   up to five items, and add one verified catalog, Audius, or saved-segment item.
   It may also offer user-triggered preview or render actions. The backend
   verifies identifiers, ownership, discovery provenance, bounds, revision,
   duration arithmetic, BPM calculations, and whether the plan makes a real
   change. The UI never applies an edit until the user selects **Confirm and
   apply plan**.

Studio inference always enables the model's thinking mode and uses
`STUDIO_AI_KEEP_ALIVE=-1`, so Ollama keeps the model loaded. The main-page
classification call also keeps the model loaded, but its thinking mode is off
by default because that short classification has a much smaller timeout.

### Music Identity metric definitions

The owner and permitted public-profile views use the same server-side period
filter (`7d`, `30d`, `6m`, or `all`). The three segment-specific proposal
metrics are calculated from server-resolved listening events, not values sent
by the browser:

- **Most-replayed segment:** eligible plays are grouped by persisted segment
  ID (or source-track ID plus selected bounds for a live DJ moment). A result
  appears after the second play; replay count is play count minus one.
- **Average segment length:** the event-weighted average of selected end second
  minus selected start second for positive segment plays.
- **Time saved versus full songs:** the sum of full source-track duration minus
  seconds actually heard, floored at zero, for positive plays whose source
  duration is known.

The API returns these values under `segment_analytics` in the Music Identity
response. Empty states are explicit, and the UI repeats each formula in an
accessible help tooltip.

### CueMix Studio

Authenticated users open `/studio` to search owned/public catalog music or
Audius, preview and save exact millisecond-bounded moments, and arrange those
saved moments into revision-controlled drafts. Each mix item snapshots its
source bounds and metadata, so editing or deleting the library item cannot
silently change an existing draft. Cut, crossfade, and fade-in/out controls
have deterministic compatibility factors and real audio previews. A render is
tied to one revision and runs on the existing bounded media queue; publishing
requires the current revision and makes that version immutable. Editing
continues by duplicating it into a new draft.

The segment editor renders a full-track WaveSurfer waveform against Studio's
existing audio element. Its draggable selection, playhead seeking, exact
numeric fields, and set-current buttons share one millisecond range. Persisted
highlight/phrase analysis appears as overlays, and grounded assistant bounds
can be played, compared, applied, or rejected without silently replacing the
user's selection. The server remains authoritative for ownership and bounds;
the numeric controls remain usable if waveform loading or decoding fails.
The ownership contract and deployment acceptance matrix are recorded in
[docs/studio-waveform-qa.md](docs/studio-waveform-qa.md).

Audius moments can be saved, arranged, previewed, privately rendered, and
published without republishing provider audio as a CueMix-owned asset. A mix
containing provider segments becomes an immutable playback manifest: the public
player resolves and streams each Audius segment live with provider attribution
and a link to the original track. Mixes containing only owned/catalog audio
publish a durable rendered asset. Auto-mix uses saved moments, named modes, and
bounded/decayed behavioral signals, and always returns an ordinary editable
draft.

`studio-ai-service` is reachable only by the backend over the Compose network.
It shares the existing Ollama model and Redis concurrency controls, receives a
bounded authoritative context, and returns schema-constrained suggestions; it
has no database access and never mutates a draft. If it or Ollama is down, the
chat reports unavailable while every manual Studio feature keeps working.

The frontend sends the most recent 12 chat messages on each request, which
supports follow-up questions while the Studio page remains open. The service
itself is intentionally stateless. In the current branch the conversation is
not persisted across a browser refresh or a new device; this is listed under
[Known limitations](#known-limitations) instead of being presented as durable
memory.

## Repository layout

```text
Project/
├── backend/
│   ├── alembic/                 Database migrations
│   ├── app/
│   │   ├── coldseed/            Repeatable course/demo dataset
│   │   ├── database/            SQLAlchemy models and sessions
│   │   ├── pipeline/            AI-DJ stages and contracts
│   │   ├── routers/             HTTP and WebSocket endpoints
│   │   ├── services/            Domain, audio, queue, and provider logic
│   │   └── main.py              FastAPI application
│   ├── scripts/                 Evaluations and operational helpers
│   └── tests/                   Backend and integration tests
├── frontend/
│   ├── e2e/                     Playwright journeys
│   ├── scripts/                 System stress runner
│   └── src/                     SvelteKit routes, components, stores, and clients
├── studio-ai-service/           Isolated internal LLM service and tests
├── deploy/                      Caddy, deployment, backup, restore, and VM checks
├── docs/                        Focused design and QA records
├── docker-compose.yml           Complete local stack
├── docker-compose.prod.yml      Complete production stack
├── .env.example                 Local configuration template
├── SECURITY.md                  Security policy and accepted provider risk
└── README.md                    This guide
```

The Git repository root is one directory above `Project/`; GitHub workflows
therefore live in `../.github/workflows/` and refer to application paths with a
`Project/` prefix.

## Development without the full stack

Compose is the supported end-to-end environment. For faster frontend work, run
only PostgreSQL and Redis in containers and start the API and Vite on the host.
This mode disables both Ollama features unless a host-accessible Ollama and the
Studio service are configured separately.

Host development additionally needs Python 3.11, Node.js 22 with npm, and
FFmpeg for compressed-audio analysis and rendering. On Ubuntu/WSL, activate a
virtual environment with `source .venv/bin/activate` and use `export NAME=value`
instead of the PowerShell environment assignments below.

### Backend on Windows PowerShell

```powershell
docker compose up -d postgres redis

cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --requirement requirements-dev.txt

$env:DATABASE_URL = "postgresql+psycopg2://cuemix_user:cuemix_dev_password@127.0.0.1:5432/cuemix_db"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:SECRET_KEY = "local-development-secret-replace-before-sharing"
$env:VIBE_LLM_PROVIDER = "none"

python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 5000
```

### Frontend

In a second terminal:

```powershell
cd frontend
npm ci
$env:PUBLIC_API_PROXY_TARGET = "http://127.0.0.1:5000"
npm run dev
```

Vite serves the development UI at <http://localhost:5173> and proxies `/api`
to the backend. The production frontend is a static build served by an
unprivileged Nginx container.

### Database changes

After modifying SQLAlchemy models, generate and inspect a migration before
applying it:

```powershell
cd backend
python -m alembic revision --autogenerate -m "describe the change"
python -m alembic upgrade head
python -m alembic check
```

Never edit an already-deployed migration to represent a new schema change;
add a new migration instead.

## Configuration

`.env.example` is the authoritative local template. Copy it to `.env`; Compose
loads it automatically. `.env` is ignored by Git and must never be committed.

| Area | Important variables |
| --- | --- |
| Database and ports | `POSTGRES_*`, `DATABASE_URL`, `FRONTEND_PORT`, `BACKEND_PORT`, `REDIS_PORT`, `ADMINER_PORT` |
| Authentication | `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `COOKIE_SECURE`, `COOKIE_SAMESITE` |
| Browser/API routing | `BACKEND_PUBLIC_URL`, `ROOT_PATH`, `CORS_ORIGINS`, `TRUST_PROXY_HEADERS` |
| Main prompt LLM | `VIBE_LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_MAX_CONCURRENCY`, `OLLAMA_THINK_ENABLED`, `OLLAMA_KEEP_ALIVE` |
| Studio AI | `STUDIO_ENABLED`, `STUDIO_AI_URL`, `STUDIO_AI_TIMEOUT_SECONDS`, `STUDIO_AI_MODEL_TIMEOUT_SECONDS`, `STUDIO_AI_MAX_CONTEXT_ITEMS`, `STUDIO_AI_MAX_OUTPUT_TOKENS`, `STUDIO_AI_TEMPERATURE`, `STUDIO_AI_INTERNAL_TOKEN` |
| Uploads | `UPLOAD_WORKERS`, `UPLOAD_QUEUE_CAPACITY`, `UPLOAD_JOB_TTL_SECONDS`, `CATALOG_AUDIO_MAX_MB_COMPRESSED`, `CATALOG_AUDIO_MAX_MB_LOSSLESS` |
| Demo/test data | `ENABLE_COLD_SEED`, `COLD_SEED_VERSION`, `COLD_SEED_RANDOM_SEED` |
| Optional/debug behavior | `ENABLE_PIPELINE_DEBUG`, `DEBUG_DASHBOARD_ENABLED`, `AUDIUS_ANALYSIS_CACHE_ENABLED` |

Replace `SECRET_KEY`, database credentials, and `STUDIO_AI_INTERNAL_TOKEN` with
long random values anywhere beyond a private developer machine. Only enable
`TRUST_PROXY_HEADERS` behind a proxy that overwrites forwarded headers. The
production values and comments in `deploy/.env.production.example` explain the
VM-specific choices.

## Testing

```powershell
cd backend
python -m pip install --requirement requirements-dev.txt
python -m alembic upgrade head
python -m alembic check
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
pytest ../studio-ai-service/tests -q

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

For a bounded load check against a running deployment:

```powershell
cd frontend
npm run test:system-stress -- --base-url http://localhost:8080 --users 20 --expected-upload-workers 4
```

Against a local or test HTTPS endpoint with a self-signed certificate, add
`--insecure`. Do not point the stress test at production unless the test data
and request volume have been explicitly approved.

Backend unit tests use an isolated temporary SQLite database by default, while
CI also exercises PostgreSQL and Redis. Every feature or bug fix should include
the smallest relevant unit or integration regression test; behavior that spans
the browser and real API belongs in Playwright.

### Optional LLM and preference evaluations

```powershell
cd backend
python -m scripts.eval_preferences
python -m scripts.eval_llm_reasoning
```

`eval_preferences` runs a deterministic labeled precision-at-K comparison to
check that learned energy preferences improve candidate ranking. It does not
need Ollama. `eval_llm_reasoning` sends a real multi-turn exchange to the
configured Ollama model and checks both context retention and tempo arithmetic;
it requires a reachable, already-downloaded model and is intentionally outside
the normal mocked `pytest` gate.

The ordinary Playwright command runs the production frontend against
controlled API fixtures. GitHub Actions also provisions a real PostgreSQL,
Redis, FastAPI, and production frontend stack and runs
`realtime-integration.spec.js`, `profile-integration.spec.js`,
`memory-integration.spec.js`, and `full-journey-integration.spec.js`. That real
suite covers both the complete coaching-memory journey and a full product
journey: register, upload and analyze multiple real WAV files, edit/preview/
render/publish a Studio mix, play it from Library, and verify the resulting
Profile analytics. Container builds, image publishing, and Azure deployment
wait for both the ordinary checks and this real-backend suite to pass. After
building the three production images, CI also starts the real production
Compose topology (Caddy, frontend, backend, Studio AI, PostgreSQL, and Redis),
repeats the full journey through Caddy over HTTPS, and runs a bounded 20-user
stress gate. That workload covers registration/login, Community posts,
parallel audio uploads, friendships/messages, DJ sessions, the configured
four-worker upload limit, deliberate 429 throttling, and recovery after the
rate-limit window; any unexpected 5xx response or timeout fails deployment.
On the Azure VM, the final deployment gate also requires Ollama to be ready,
the configured local model to be installed and loaded, and one real Studio edit
plan to complete successfully within the production timeout.

To point those real integration files at an already-running stack manually,
set `PLAYWRIGHT_BASE_URL` to its frontend origin and
`PLAYWRIGHT_BACKEND_URL` to its backend API origin before invoking Playwright.
The CI workflow supplies both automatically and uses an ephemeral test
database, so CI runs do not modify production data.

Do not commit `.env`, virtual environments, `node_modules`, model downloads,
or unlicensed audio. Runtime demo playback uses an original, procedurally
generated `cuemix-demo.wav` (see [backend/app/static/audio/GENERATED_AUDIO.md](backend/app/static/audio/GENERATED_AUDIO.md))
— no third-party sample.

## CI/CD and production

The primary workflow is
[`../.github/workflows/cuemix-ci-cd.yml`](../.github/workflows/cuemix-ci-cd.yml).
It runs for every push and pull request and contains these gates:

1. Backend migrations, tests, Studio AI tests, and an 80% backend coverage
   minimum.
2. Svelte checks, formatting/ESLint, dependency audit, unit tests, production
   build, and fixture-backed Playwright tests.
3. Real PostgreSQL/Redis/backend/frontend WebSocket and browser journeys.
4. Development and production Compose validation, all three application image
   builds, a Caddy-based HTTPS journey, and the bounded system stress test.
5. On `main`, publication of immutable commit-SHA images to GHCR.
6. When repository variable `VM_DEPLOY_ENABLED=true`, deployment to the
   protected `production` environment and a hard local-LLM acceptance check.

Production is currently served at
<https://sweng-group-18.eastus.cloudapp.azure.com>. The production stack uses
Caddy, frontend, backend, Studio AI, PostgreSQL, Redis, Ollama, and persistent
database/upload/model/proxy volumes. Production deliberately uses one Uvicorn
process and four upload worker threads. The active upload dispatcher is still
process-local, so increasing `BACKEND_WORKERS` would allow workers to disagree
about active jobs even though Redis preserves job durability.

### One-time VM and repository setup

The deployment target needs Docker Engine with Compose v2, a DNS record pointed
at the VM, and inbound TCP ports 22, 80, and 443 plus UDP 443. Create
`~/cuemix-deploy/.env` from `deploy/.env.production.example`, replace every
placeholder secret, and keep that file only on the VM.

Configure these GitHub repository or production-environment variables:

- `VM_DEPLOY_ENABLED=true`
- `SSH_HOST`
- `SSH_USER`
- `GHCR_USERNAME`
- `PUBLIC_BASE_URL` beginning with `https://`

The workflow also manages `AUDIUS_ANALYSIS_CACHE_ENABLED=true`,
`DEBUG_DASHBOARD_ENABLED=false`, and `ENABLE_PIPELINE_DEBUG=false` by default.
Repository variables with those names may override the three feature flags.
`BACKEND_WORKERS` remains pinned to `1` until the upload queue is fully
distributed; a stale repository value cannot raise it.

Configure these GitHub production-environment secrets:

- `SSH_PRIVATE_KEY`
- `GHCR_READ_TOKEN`

Protect `main` and the `production` environment with the required CI checks and
review policy appropriate for the course team. The workflow and scripts cannot
enforce branch protection themselves; that is a repository-admin setting.

The deployment script synchronizes the Compose and operational files, refreshes
those managed settings and the non-secret Studio runtime contract in the VM's
persistent `.env`, logs the VM into GHCR, pulls the exact SHA-tagged images,
migrates the database, starts the stack, pulls and warms the configured Ollama
model, and runs `deploy/verify-local-llm.sh`. It leaves the operator-selected
model and secret Studio token untouched. Deployment fails unless Ollama is
reachable, the model is installed and resident, Studio reports ready, and one
real schema-validated planning request succeeds within the production timeout.

## Operations

### Health and logs

From `~/cuemix-deploy` on the VM:

```bash
docker compose --env-file .env --file docker-compose.prod.yml ps
docker compose --env-file .env --file docker-compose.prod.yml logs --tail=200 backend studio-ai-service ollama redis
curl --fail https://sweng-group-18.eastus.cloudapp.azure.com/api/db-health
```

The database health response also reports Redis reachability. The separate
[`../.github/workflows/uptime-check.yml`](../.github/workflows/uptime-check.yml)
runs every 15 minutes, opens or updates a GitHub issue labeled `uptime` when the
probe fails, and closes the issue after recovery. GitHub scheduling can be
delayed, so this is an incident signal rather than a strict uptime SLA.

### Backups and restore drills

`deploy/remote-deploy.sh` installs an idempotent daily 03:00 UTC cron entry.
`deploy/backup.sh` saves a compressed PostgreSQL dump and the uploads volume in
`~/cuemix-backups`, retaining 14 days by default. Run an additional backup with:

```bash
cd ~/cuemix-deploy
DEPLOY_ROOT="$PWD" bash deploy/backup.sh
```

These backups live on the same VM. Copy them to access-controlled off-VM
storage for real disaster recovery.

Prefer the automated scratch restore drill, which backs up, restores into a
separate database and Docker volume, verifies non-empty restored data, and
cleans up without touching production:

```bash
cd ~/cuemix-deploy
DEPLOY_ROOT="$PWD" DRILL_ID="manual-$(date +%s)" bash deploy/backup-restore-drill.sh
```

The same drill can be started from the **Cuemix CI** workflow with
`run_backup_drill=true`. `deploy/restore.sh` defaults to live targets when no
scratch names are supplied, so inspect its arguments and take a fresh backup
before any live restore.

### Rollback

Run **Cuemix CI** manually with `rollback_sha` set to a full commit SHA whose
images were already published. The rollback redeploys those immutable app
images without rebuilding them. It does not reverse database migrations or
restore data, so schema compatibility must be checked before using it.

## Security and data handling

- Authentication uses an HTTP-only cookie rather than browser local storage;
  unsafe cookie-authenticated requests are checked for cross-site origins.
- Passwords are hashed and authentication/write endpoints are rate limited.
- Server-side ownership and visibility checks protect private mixes, Studio
  resources, profiles, messages, attachments, and WebSocket subscriptions.
- Upload size/type validation, audio decoding, and server-resolved bounds run
  before catalog or Studio data becomes authoritative.
- The internal Studio AI endpoint may use a shared secret and is not exposed by
  either reverse proxy. Assistant output is untrusted until backend validation.
- Raw Audius audio used for enabled analysis is temporary and deleted after the
  analysis attempt; only provider metadata and derived analysis are persisted.
  The project owner accepted the remaining contractual risk on 2026-08-20,
  but this is not written individualized approval from Audius.

Read [SECURITY.md](SECURITY.md) for private vulnerability reporting, dependency
exceptions, the exact Audius compliance decision, and its remaining
license/attribution gap. Never commit `.env`, SSH keys, database dumps, uploaded
media, access tokens, the Ollama volume, virtual environments, or
`node_modules`.

## Known limitations

- CueMix does not contain a trained ranking or recommendation model. Candidate
  ranking is deterministic; the main-page LLM only refines prompt structure.
- Live DJ sessions render one segment at a time. Transition plans shown there
  are explanatory metadata; rendered multi-track Studio mixes perform audible
  crossfades.
- Studio chat context is limited to the 12 most recent messages in the open
  page and is lost on refresh. There is currently no durable conversation
  history and no proactive per-segment advice tab.
- The assistant performs bounded analysis and edit planning. It cannot browse
  the web, upload or create music, edit arbitrary database fields, publish
  autonomously, or bypass the confirmation and validation flow.
- Provider-backed public mixes are manifests rather than permanent composite
  audio files. Playback depends on the provider still serving each source, and
  the project still does not capture a per-track Audius license field.
- Manual Studio continues to work if Ollama or Studio AI is unavailable. The
  main-page parser also falls back to deterministic interpretation, so LLM
  outages do not take down the application.
- The active upload queue is process-local. Keep `BACKEND_WORKERS=1` until
  Redis becomes the authoritative dispatcher with atomic claims and leases.
- Uploads and backups are VM-local rather than object-storage backed. True
  horizontal scaling and disaster recovery need shared object storage and
  off-VM backups.
- Authentication has expiring access cookies but no refresh-token or active
  token-revocation system. Pipeline and admin debug surfaces are off by default
  and are intended only for controlled course troubleshooting when enabled.

## Troubleshooting

### First start appears stuck

The model initializer must download and warm `qwen3:8b` before the backend and
Studio AI can become healthy. Watch it with:

```powershell
docker compose logs -f ollama-model-init ollama
```

Later starts reuse the `ollama_data` volume. Avoid deleting that volume unless
a full model re-download is acceptable.

### Studio assistant says unavailable

Check service state and the model before changing application code:

```powershell
docker compose ps
docker compose logs --tail=200 backend studio-ai-service ollama ollama-model-init redis
docker compose exec ollama ollama list
docker compose exec ollama ollama ps
```

The expected model name must match `OLLAMA_MODEL`, and Studio `/ready` requires
it to be installed. A response can also be rejected when it is not valid JSON,
mentions stale or foreign IDs, violates bounds, targets the final outgoing
transition, or proposes no actual change; the safe result is an unavailable
recommendation and an unchanged draft.

### Docker or VmmemWSL is using too much memory

Ollama is configured to keep the model resident, so high WSL memory use after
inference is expected. Stop this project's containers with `docker compose
down`. If all WSL work may be stopped too, run `wsl --shutdown` from Windows
PowerShell after Compose is down. Starting Docker again will recreate the WSL
VM; starting CueMix will reload the model when needed.

### A port is already in use

Change `FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, or
`ADMINER_PORT` in `.env`, then recreate the affected containers. The browser
normally needs only the frontend port because it reaches the API through
`/api`.

### Database schema errors after pulling changes

```powershell
docker compose run --rm migrate
docker compose up -d
```

The normal `docker compose up` path also waits for migrations automatically.
Do not delete the database volume just to work around a migration failure;
inspect the migration error first.

### A provider-backed mix will not publish or play

CueMix publishes Audius mixes as playback manifests, never as permanent
composite audio. Publication rejects an unavailable/known-broken provider track
or invalid segment metadata. After publication, individual segments may still
become unavailable if Audius no longer serves them; the public player reports
that state and continues with any segments it can resolve. Remove or replace a
broken source and publish a new revision.
