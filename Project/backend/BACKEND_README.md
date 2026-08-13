# Zonix backend

This directory contains the FastAPI, SQLAlchemy, Alembic, and PostgreSQL side
of Zonix. It implements a complete prototype API for authentication, persistent
DJ sessions and preferences, mix publishing, forum interactions, profiles,
direct messages, notifications, and bounded media uploads.

Zonix still does not render real crossfades or run a trained music-selection
model. Audius supplies candidate metadata and streams when available; a small,
original WAV file is the deterministic offline fallback.

## Run it

The supported local path starts at the project root:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose starts PostgreSQL, applies `alembic upgrade head` in a one-shot
migration service, and waits for the database and API health checks before
serving the frontend at <http://localhost:8080>. API documentation is available
at <http://localhost:8080/api/docs>.

To run only the Python application from `backend/`, provide `DATABASE_URL` and
`SECRET_KEY`, then run:

```powershell
python -m pip install --requirement requirements-dev.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 5000
```

Do not create or change tables manually in Adminer. Models and an Alembic
migration must land together.

## API areas

- `/auth`: register, login, logout, and current-user lookup.
- `/sessions`: start, retrieve, give feedback to, and stop persistent sessions.
- `/mixes`: generate, retrieve, edit, publish, like, save, and list feed/library
  mixes.
- `/posts`: forum feed, posts, comments, reversible votes, and author deletion.
- `/users`: editable profile, learned preferences, and public activity stats.
- `/messages`: private conversation history and direct-message creation.
- `/notifications` and `/ws/notifications`: durable notification history plus
  live delivery while the process is connected.
- `/uploads`: bounded raw/batch upload jobs and permission-checked media serving.
- `/health`, `/db-health`, and `/model-info`: liveness, database readiness, and
  an honest description of the current selector.

FastAPI's generated `/docs` page is the canonical field-level contract.

## Security model

- Authentication is stored in an HTTP-only JWT cookie. Production always sets
  the cookie `Secure`; `SameSite=None` also forces it.
- Cookie-authenticated writes are protected by origin and Fetch Metadata checks.
- New passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations. Existing
  bcrypt or lower-cost PBKDF2 hashes remain verifiable and are replaced after a
  successful login.
- Production startup rejects short and recognizable placeholder JWT secrets.
- Auth and write endpoints have sliding-window limits keyed by matched route
  template and client identity. Storage is process-local, so multiple replicas
  require a shared limiter such as Redis.
- Uploads enforce media allowlists, byte signatures, declared and streamed size
  limits, owner checks, and private cache headers. The reverse proxies also cap
  request bodies at 10 MiB.
- Anonymous forum response objects and notifications do not expose the author.
- Structured access events include a request ID; secrets and request bodies are
  not logged.

Use a generated secret in deployment, for example `openssl rand -hex 32`. Keep
`.env` out of Git.

## Persistence and processing

SQLAlchemy models cover users, profiles, preferences, sessions, feedback,
mixes, segments, likes/saves, posts, comments, votes, attachments, direct
messages, and notifications. PostgreSQL is the intended runtime database;
SQLite is used only for isolated migration and unit-test checks.

The upload queue is deliberately bounded and processes work concurrently, but
job state and WebSocket fanout are currently in one backend process. Attachment
rows and completed files are persistent. Production therefore defaults to one
Uvicorn worker until the queue, pub/sub, and limiter move to durable shared
infrastructure.

Uploads are validated by size, declared type, extension, and file signature.
They are not yet decoded with a media codec or analyzed for tempo/key/content.
The per-file limit is 10 MiB and the decoded batch limit is 7 MiB.

## Selection behavior

`prompt_parser.py` provides deterministic intent parsing. An LLM can
optionally classify a bounded set of moods, energy levels, vocals, and
genres, but its output cannot invent playable catalog items. Invalid,
unavailable, or timed-out LLM responses fall back to deterministic parsing.
Which provider runs is `VIBE_LLM_PROVIDER` (`groq` by default, or `ollama` /
`none`) — see [AI_DJ_PIPELINE.md](../AI_DJ_PIPELINE.md) for the full
breakdown of both.

`audius_service.py` searches the external catalog defensively. Provider errors
or malformed nested fields produce a controlled local fallback instead of a
server error. The current mix plan uses metadata and fixed time windows; it is
not audio segmentation, beat matching, crossfading, or a trained recommender.

## Migrations and tests

Run the backend quality gate from this directory:

```powershell
python -m pip install --requirement requirements-dev.txt
python -m alembic upgrade head
python -m alembic check
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
```

The suite covers auth and hash migration, access control, persistence, social
interactions, anonymous privacy, upload limits/backpressure, provider failure,
health endpoints, and migration drift. CI runs the same checks against a
PostgreSQL service.

When a model changes:

1. Import it from `app/database/models/__init__.py`.
2. Generate and review a migration.
3. Upgrade a fresh database.
4. Run `python -m alembic check` and the test suite.

## Optional demo seed

Demo forum content is opt-in, labeled, idempotent, and never runs at startup:

```powershell
docker compose exec -e ALLOW_DEMO_SEED=true backend python -m app.seed
```

This creates only `.invalid` demo accounts and `[Demo]` forum content. Do not
enable it silently in production.

## Operations

- `python -m app.cleanup_uploads` reports orphaned upload files.
- Stop the backend, then `python -m app.cleanup_uploads --delete
  --confirm-backend-stopped` removes confirmed orphans; review the dry-run
  output first. The stop confirmation protects completed jobs whose database
  row has not yet been materialized.
- Set `TRUST_PROXY_HEADERS=true` only when direct backend access is blocked and
  the trusted proxy replaces forwarding headers.
- Groq (the default LLM provider) only needs `GROQ_API_KEY` set. Ollama is
  opt-in (`VIBE_LLM_PROVIDER=ollama`); see the root guide for the exact
  profile and model-pull commands — no multi-gigabyte model downloads happen
  automatically.

For full architecture, deployment prerequisites, current limitations, and the
MLOps roadmap, use [the canonical project guide](../ZONIX_PROJECT_README.md).
