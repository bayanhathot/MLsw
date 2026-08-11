# Zonix

Zonix is a full-stack prototype for a prompt-guided DJ experience. The current
application provides a SvelteKit UI, a FastAPI/PostgreSQL API, cookie-based
authentication, persistent sessions and feedback, an Audius-backed mix plan
with a local fallback, mix/forum/social vertical slices, protected uploads,
and local Docker orchestration.

It is **not yet a trained AI DJ or an audio mixing engine**. The current player
plays source/demo audio; it does not analyze waveforms or render real
crossfades. The repository includes a clearly labeled offline ranking baseline
so later ML work can be evaluated rather than guessed.

## Run the application

Requirement: Docker Desktop with Compose v2.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose waits for PostgreSQL, runs `alembic upgrade head` once, then starts the
healthy backend and frontend. Open:

- App: <http://localhost:8080>
- API docs: <http://localhost:8080/api/docs>
- Database health: <http://localhost:5000/db-health>

Stop containers without deleting database data:

```powershell
docker compose down
```

Delete the `postgres_data` volume only when you intentionally want a clean
database: `docker compose down --volumes`.

Demo forum data is opt-in, idempotent, and never created during startup. Use it
only in a local/demo database:

```powershell
docker compose exec -e ALLOW_DEMO_SEED=true backend python -m app.seed
```

### Optional tools

Adminer is excluded from normal startup:

```powershell
docker compose --profile tools up -d postgres adminer
```

The prompt parser has a deterministic fallback. To additionally run the local
Ollama classifier, start the profile and explicitly download the configured
model (the repository does not download multi-gigabyte models automatically):

```powershell
docker compose --profile ai up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b
```

After the pull succeeds, set these two values in `.env`, then start the stack:

```dotenv
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
```

```powershell
docker compose --profile ai up --build
```

If Ollama is missing, unavailable, slow, or returns invalid JSON, prompt
classification safely falls back to deterministic rules. Only catalog tracks
can become playable results.

## Architecture

```text
browser
  -> Nginx static frontend
       -> /api/* same-origin proxy
            -> FastAPI
                 -> PostgreSQL
                 -> named attachment volume
                 -> Audius search (controlled local fallback)
                 -> Ollama (optional intent classification)
```

The frontend uses `/api` rather than a hardcoded localhost backend. Nginx
strips that prefix before forwarding requests. This makes cookies, static audio
URLs, and deployments work from a single origin.

Main API groups:

- `/auth`: register, login, logout, and current-user lookup.
- `/sessions`: create/read a persistent session, record feedback, and stop it.
- `/mixes`: create persisted segment plans; manage a library; publish, browse,
  like, and save mixes.
- `/posts`: create/read posts and comments, post anonymously, attach media, and
  apply reversible votes.
- `/users`: read/update the current profile, preferences, and engagement stats.
- `/messages`, `/notifications`, and `/ws/notifications`: protected direct
  messages, durable notification history, and live notification delivery.
- `/uploads`: validated single/batch attachment jobs and protected inline
  retrieval. The bounded priority queue is in-process; file bytes persist.
- `/db-health`: checks the API-to-PostgreSQL connection.

## Development checks

Backend (Python 3.11):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --requirement requirements-dev.txt
python -m alembic upgrade head
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
```

When running outside Compose, export `DATABASE_URL` and `SECRET_KEY`; use the
host database URL documented as `DATABASE_URL_LOCAL` in `.env.example`.

Frontend (Node 22):

```powershell
cd frontend
npm ci
npm run check
npm test
npm run lint
npm audit --audit-level=moderate
npm run build
npx playwright install chromium # first run on a developer machine
npm run test:e2e
```

The GitHub Actions workflow is installed at the repository root. It runs
migrations/tests, Svelte checks, formatting, linting, dependency audit, the
lightweight reproducible ML baseline, production build and Chromium route
smoke tests, Compose validation, and both container builds. Its first hosted
result requires a push or pull request. Protect `main` and require these checks
before merging.
Backend coverage is gated at 80% (the current CI-like run is 88.04%). Ratchet
the gate upward as WebSocket and queue internals gain deterministic tests
rather than weakening it when coverage falls.

## ML/MLOps baseline

See [ML_PIPELINE.md](ML_PIPELINE.md). In short:

```powershell
python -m venv .ml-venv
.\.ml-venv\Scripts\Activate.ps1
python -m pip install --requirement requirements-ml.txt
dvc repro
dvc metrics show
mlflow ui --backend-store-uri ./mlruns
```

The sample catalog is synthetic and its metrics are only a pipeline smoke test.
There is no configured DVC remote, no production dataset, and no promoted model
artifact. Real experiments must record licensed-data provenance, Git revision,
parameters, metrics, and artifacts in MLflow.

## Course-feedback status and next milestones

| Requirement | Current truth | Next completion criterion |
| --- | --- | --- |
| Core proposal | Working prompt/session/player vertical slice | Analyze real segments and render/test actual transitions; add the promised modes and analytics |
| Long-term memory | Authenticated feedback is persisted as user preference strength and exposed on the profile UI | Verify that preferences improve ranked results with a labeled evaluation |
| Hallucination robustness | Provider/local catalog boundaries and deterministic fallback; offline silence/catalog-integrity metrics | Compute silence features for the production catalog and reject every unknown segment ID at the API boundary |
| Upload job queue | Raw single and JSON-base64 batch upload endpoints, type/signature/size validation, bounded parallel priority queue, status polling, protected media, UI uploader, and persistent file volume | Add durable Redis-backed job state, retries/cancellation/progress, codec decoding, object storage, and restart/load tests |
| Local LLM | Optional Ollama intent parser with deterministic fallback | Benchmark the chosen model and add bounded concurrency/load tests; never let LLM text create catalog records |
| Forum/communication | Mix feed/library, likes/saves, posts/comments/votes, anonymous posting, profiles, protected attachments, DMs, durable notifications, WebSocket UI, and a mocked browser route smoke suite are implemented | Expand browser E2E to mutating flows against live PostgreSQL; add accessibility tests, moderation/reporting, shared WebSocket pub/sub, and production load tests |
| CI/CD/deployment | Reproducible CI/container builds and a secrets-gated Azure/GHCR deployment template | Configure the supplied host/domain and protected secrets, perform the first deploy, test rollback, and add an external uptime check |

The safest order is: keep CI green, exercise migrations and social/upload flows
against live PostgreSQL in browser E2E tests, make queue and notification state
durable, prove catalog/segment quality, then implement real audio transitions.
Deployment should not be reported complete until the first protected rollout,
rollback drill, backups, and external uptime check succeed.

## Repository hygiene and security

- Never commit `.env`, private keys, credentials, model downloads, DVC caches,
  virtual environments, `node_modules`, or generated build output.
- Runtime demo playback uses the original procedural `zonix-demo.wav`, which is
  reproducible with the committed generator. The old uncleared MP3 has been
  removed from the current revision and images; its ordinary blob remains only
  in old Git history pending a separately coordinated rewrite. Future MP3
  staging is assigned to Git LFS.
- Local Compose defaults are development-only. Replace the database password
  and `SECRET_KEY`, enable secure cookies, and terminate TLS before deployment.
- Do not expose PostgreSQL, Adminer, Ollama, or MLflow publicly.
- Uploaded attachments use a named local volume and must be backed up together
  with PostgreSQL. Keep one backend process until in-process WebSocket fanout
  and upload jobs are replaced by shared pub/sub and a durable queue.
