# Zonix

Zonix is a full-stack prototype for a prompt-guided DJ experience. The current
application provides a SvelteKit UI, a FastAPI/PostgreSQL API, cookie-based
authentication, persistent sessions and feedback, an Audius-backed mix plan
with a local fallback, mix/community/social-graph vertical slices, protected uploads,
raw listening-event capture, a private-by-default Music Identity analytics dashboard,
public listener profiles, and local Docker orchestration.

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
- `/users`: profile/preferences, Music Identity analytics/privacy, engagement stats, and safe public listener profiles.
- `/listening-events`: authenticated, idempotent raw playback events used by Music Identity analytics.
- `/messages`, `/notifications`, and `/ws/notifications`: protected direct
  messages, durable notification history, and live notification delivery.
- `/uploads`: validated single/batch attachment jobs and protected inline
  retrieval. The bounded priority queue is in-process; file bytes persist.
- `/db-health`: checks the API-to-PostgreSQL connection.


## Music Identity analytics

Zonix now records **actual playback time** as raw `listening_events` when an authenticated listener finishes, skips, closes, stops, or changes a played segment/session. It does not send a request every second. Track identity/artist/genre/vibe are resolved by the backend from the referenced Zonix mix segment or DJ session rather than trusted from client metadata.

The deterministic analytics service derives total listening time, top artists, artist listening shares, genre distribution, recurring vibes, a listening trend, and recent listening contexts. New and migrated users have a `user_music_profiles` row that is **private by default**. Public profile endpoints never return private Music Identity data.

The frontend provides a modern `/profile` Music Identity dashboard plus `/users/[username]` public profiles, and forum author names link into those profiles. The Listening DNA panel/API contract is present but intentionally reports `not_generated` until later ML work is implemented. See [MUSIC_IDENTITY.md](MUSIC_IDENTITY.md) for the data flow, debugging steps, and exact future ML integration point.

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
Backend coverage is gated at 80% (the current implementation run is 88.49%). Ratchet
the gate upward as WebSocket and queue internals gain deterministic tests
rather than weakening it when coverage falls.

## AI-DJ pipeline

The offline DVC/MLflow tag-overlap ranking baseline (`ml_pipeline.py`) has been
removed: nothing in the running app ever called it, and this project has no
ranking/scoring stage by design -- candidate ordering is deterministic
end-to-end. The AI-DJ request path (session start, feedback, mix generation)
is now one consolidated, swappable pipeline. See
[AI_DJ_PIPELINE.md](AI_DJ_PIPELINE.md) for the full stage-by-stage writeup,
including exactly which parts are deterministic versus the one
schema-constrained Ollama call, and what's deliberately left for later (a real
trained ranking model, if one is ever wanted).

## Course-feedback status and next milestones

| Requirement | Current truth | Next completion criterion |
| --- | --- | --- |
| Core proposal | Working prompt/session/player vertical slice | Analyze real segments and render/test actual transitions; add the promised modes and analytics |
| Long-term memory | Authenticated feedback is persisted as user preference strength and exposed on the profile UI | Verify that preferences improve ranked results with a labeled evaluation |
| Hallucination robustness | Provider/local catalog boundaries and deterministic fallback; offline silence/catalog-integrity metrics | Compute silence features for the production catalog and reject every unknown segment ID at the API boundary |
| Upload job queue | Raw single and JSON-base64 batch upload endpoints, type/signature/size validation, bounded parallel priority queue, status polling, protected media, UI uploader, and persistent file volume | Add durable Redis-backed job state, retries/cancellation/progress, codec decoding, object storage, and restart/load tests |
| Local LLM | Optional Ollama intent parser with deterministic fallback | Benchmark the chosen model and add bounded concurrency/load tests; never let LLM text create catalog records |
| Community/communication | Friends, search/discovery, public profiles, mix feed/library, native mix sharing, Friends/Explore/Discussions feeds, posts/comments/votes, anonymity in Discussions, protected attachments, friend-only DMs, durable notifications, block/report infrastructure, and WebSocket UI are implemented | Expand browser E2E to mutating flows against live PostgreSQL; add accessibility tests, moderation review UI, shared Redis WebSocket pub/sub, pagination/load tests, and later collaborative mixes |
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
