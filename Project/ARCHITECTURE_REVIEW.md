# Zonix Architecture and Project Review

**Review date:** 2026-08-15  
**Scope:** Current working tree, including the uncommitted Phase C session-prefetch work  
**Review type:** Read-only architecture, behavior, quality, security, testing, and deployment review

## Executive summary

Zonix is a substantial full-stack course prototype implemented as a modular
monolith. It combines a client-rendered SvelteKit SPA, one FastAPI application,
PostgreSQL, persistent file storage, Audius retrieval, optional local Ollama
classification, librosa audio analysis, and pydub/ffmpeg rendering.

The codebase is coherent, thoughtfully separated, and unusually well tested for
a prototype. It already contains complete vertical slices for authentication,
prompt-guided sessions, persisted mixes, catalog uploads, community posts,
social relationships, direct messages, notifications, attachments, listening
telemetry, and Music Identity analytics.

It is not yet a production-ready or horizontally scalable service, and it is not
a trained AI DJ. Its intelligent behavior consists of deterministic parsing and
ranking heuristics, optional LLM classification, and audio signal processing.

One distinction is especially important:

- Persisted mixes are rendered as real multi-track WAV files with crossfades.
- Live DJ sessions render one segment at a time. Their BPM/key transition plan
  is currently explanatory metadata and is not applied as an audible crossfade
  between consecutive live tracks.

The current Phase C prefetch implementation should not be merged as-is. It has
backend and frontend concurrency races that can consume stale prepared tracks,
repopulate state after stop, lose request-controller ownership, and leak rendered
files.

## System architecture

```text
Browser
|-- SvelteKit client-side SPA
|   |-- page routes and UI components
|   |-- auth, live-session, and global-player stores
|   `-- resource-specific API adapters
|
|-- Development: frontend Nginx on :8080
|   `-- /api/* -> FastAPI on :5000
|
`-- Production: Caddy on :80/:443
    |-- /api/* -> FastAPI
    `-- other paths -> Nginx static frontend

FastAPI modular monolith
|-- authentication and request security
|-- sessions, mixes, catalog, and rendering
|-- community, profiles, social graph, and messaging
|-- uploads, listening analytics, and debug endpoints
|-- AI-DJ pipeline
|   |-- optional local Ollama
|   |-- Audius search and streams
|   |-- local PostgreSQL catalog
|   `-- librosa + pydub/ffmpeg
|-- PostgreSQL
`-- persistent uploads/renders volume
```

The FastAPI app, middleware, and domain routers are assembled in
[`backend/app/main.py`](backend/app/main.py#L57). The frontend is explicitly a
client-rendered SPA with SSR and prerendering disabled in
[`frontend/src/routes/+layout.js`](frontend/src/routes/+layout.js#L5).

### Architectural style

Zonix is a modular monolith rather than a microservice system:

- The frontend is compiled to static assets and served by Nginx.
- All API domains run inside one FastAPI process.
- PostgreSQL is the authoritative structured-data store.
- Uploaded and generated media live in a Docker named volume.
- Audius and Ollama are external/runtime dependencies, not separate Zonix
  business services.
- Background jobs, WebSocket fanout, caches, and rate limits are process-local.

This is an appropriate shape for a prototype and single-VM deployment. It also
defines the current scaling boundary: adding backend workers or replicas before
introducing shared coordination infrastructure will create inconsistent state.

## Repository map

| Location | Responsibility |
| --- | --- |
| `frontend/src/routes/` | Eleven SPA routes and page-level controllers |
| `frontend/src/lib/components/` | Twenty-one reusable UI and player components |
| `frontend/src/lib/services/` | Shared HTTP client and twelve resource adapters |
| `frontend/src/lib/stores/` | Authentication, live-session, and global-mix state |
| `backend/app/routers/` | Twelve API router modules |
| `backend/app/services/` | Business logic, analytics, queues, and AI-DJ pipeline |
| `backend/app/database/models/` | Twenty-three SQLAlchemy model classes |
| `backend/alembic/` | Linear PostgreSQL migration history |
| `backend/tests/` | API, service, security, pipeline, and persistence tests |
| `deploy/` | Caddy, remote deployment script, and production instructions |
| `.github/workflows/` | CI, image publishing, and gated Azure deployment |

## Frontend architecture

### Application shell and state

The root layout loads global styling, mounts the navbar and global persisted-mix
player, and performs the initial cookie-authentication check in
[`frontend/src/routes/+layout.svelte`](frontend/src/routes/+layout.svelte#L23).

Most route state is local Svelte 5 rune state. Cross-route state is limited to
three stores:

- `authStore` tracks `checking`, `guest`, and `authenticated` states. It protects
  against stale authentication requests and never stores the JWT in browser
  storage.
- `sessionStore` owns the live AI-DJ lifecycle: start, feedback, automatic
  advance, playback intent, media events, stop, reset, and the current prefetch
  work. See
  [`frontend/src/lib/stores/sessionStore.js`](frontend/src/lib/stores/sessionStore.js#L41).
- `playerStore` holds the persisted/public mix selected for the layout-level
  mini-player. See
  [`frontend/src/lib/stores/playerStore.js`](frontend/src/lib/stores/playerStore.js#L10).

Every HTTP request passes through
[`frontend/src/lib/services/api.js`](frontend/src/lib/services/api.js#L126),
which supplies:

- `/api` as the same-origin default.
- Cookie credentials.
- AbortSignal propagation and a default 15-second timeout.
- FastAPI error-body normalization.
- Safe rewriting of backend media URLs.

Resource adapters then provide domain-specific functions for sessions, mixes,
profiles, forum posts, social relationships, messages, uploads, listening
events, authentication, and debug information.

### Route behavior

| Route | Main responsibility |
| --- | --- |
| `/` | Prompt composer and live DJ player |
| `/feed` | Published-mix discovery, like/save actions, and playback |
| `/library` | Generate, edit, publish, save, and play owned mixes |
| `/community` | Friends, Explore, Discussions, People, attachments, and voting |
| `/messages` | Conversation inbox and friends-only direct messages |
| `/profile` | Profile editing, preferences, and private Music Identity |
| `/users/[username]` | Public profile, mixes, friends, Music Identity, and relationship actions |
| `/login`, `/register` | Cookie-authentication flows |
| `/forum`, `/social` | Compatibility redirects |

The live player is mounted only by the home route in
[`frontend/src/routes/+page.svelte`](frontend/src/routes/+page.svelte#L125).
The saved-mix player is mounted globally by the root layout. This distinction is
the source of several media-lifecycle issues described later.

## Backend architecture

### Application composition

The backend is a synchronous SQLAlchemy/FastAPI application. A single engine and
session factory are created in
[`backend/app/database/database.py`](backend/app/database/database.py#L40), and
one database session is yielded per request.

The application includes:

- Credential-aware CORS.
- A cookie-origin guard for unsafe requests.
- Structured request logging with request IDs and durations.
- Static demo-audio serving.
- Health, database-health, and model-information endpoints.

The API domains are:

| API area | Responsibility |
| --- | --- |
| `/auth` | Register, login, logout, and current user |
| `/sessions` | Start, read, coach, advance, prefetch, and stop live sessions |
| `/mixes` | Generate, edit, publish, browse, like, and save mixes |
| `/catalog` | Authenticated catalog audio upload and playback |
| `/posts` | Community feeds, posts, comments, attachments, and votes |
| `/users` | Profiles, preferences, public data, and Music Identity |
| `/friends`, `/users/search`, `/reports` | Social graph and report records |
| `/messages`, `/notifications` | Direct messages and durable notifications |
| `/uploads` | Queued attachments, job polling, and protected media |
| `/listening-events` | Playback telemetry |
| `/debug` | Optional pipeline and Ollama observability |

Some domains have a clean router/service boundary, especially authentication,
sessions, mixes, listening, and analytics. Social, forum, messaging, and
profiles still contain substantial policy, queries, transactions, and
notification behavior directly in their routers.

### Authentication and request security

Registration normalizes identity fields, hashes the password, and creates a
private Music Identity profile atomically. Login verifies or upgrades the
password hash and stores a signed JWT in an HTTP-only cookie. Protected requests
decode the cookie, reload the user, and verify `is_active`.

Security strengths include:

- PBKDF2-SHA256 with a 600,000-round work factor.
- Transparent legacy bcrypt upgrade.
- Production rejection of short or placeholder JWT secrets.
- Restricted HMAC algorithms.
- `Secure` production cookies.
- SameSite cookie configuration.
- Cookie-origin checks and process-local rate limits.
- Ownership and visibility checks on protected media.

The implementation is in
[`backend/app/core/security.py`](backend/app/core/security.py#L21) and
[`backend/app/routers/auth.py`](backend/app/routers/auth.py#L51).

Remaining lifecycle gaps include no token revocation/version, refresh flow,
password-change invalidation, account-session management, or administrator role.

## AI-DJ and audio pipeline

The pipeline uses five swappable interfaces defined in
[`backend/app/services/pipeline/interfaces.py`](backend/app/services/pipeline/interfaces.py#L15):

```text
VibeUnderstander
    -> CandidateRetriever
    -> SegmentSelector
    -> TransitionPlanner
    -> AudioRenderer
```

Concrete implementations are bound once per process in
[`backend/app/services/pipeline/dependencies.py`](backend/app/services/pipeline/dependencies.py#L87).

### Stage 1: prompt understanding

The deterministic parser extracts:

- Mood.
- Energy.
- Vocal preference.
- Up to five known genres.
- Artist and whether the artist is required or only a reference.
- A bounded search query.

See [`backend/app/services/prompt_parser.py`](backend/app/services/prompt_parser.py#L176).

When enabled, Ollama receives the `PromptIntent` JSON schema. Calls are bounded
by a semaphore and fail open to the deterministic result on overload, timeout,
HTTP failure, invalid JSON, or schema failure. Required-artist prompts skip the
LLM because deterministic extraction is already sufficient.

Guardrails whitelist genres, preserve the deterministic/raw search query, and
prefer regex-extracted artists. Ollama remains a classification refinement; it
cannot directly create catalog records or audio.

### Stage 2: candidate retrieval and ranking

Sessions and mixes currently use multi-query Audius first and the local catalog
only when Audius returns no results.

The default Audius retriever:

1. Builds up to five artist/genre/mood/energy/raw-prompt queries.
2. Executes progressive search rounds.
3. Deduplicates candidates by provider track ID.
4. Combines rankings using Reciprocal Rank Fusion.
5. Re-ranks with deterministic weights for retrieval position, genre, mood,
   tags, approximate energy, artist similarity, and recent-artist diversity.

See
[`backend/app/services/pipeline/audius_retriever.py`](backend/app/services/pipeline/audius_retriever.py#L176).

This is a real ranking stage, but it is a handwritten scoring function rather
than a trained recommendation model.

Sessions report a no-match error if both Audius and the catalog are empty.
Mixes guarantee some output by retrying the catalog without an artist filter as
a final fallback.

### Stage 3: segment selection

Catalog uploads receive one-time librosa analysis in
[`backend/app/services/audio_analysis.py`](backend/app/services/audio_analysis.py#L74):

- Tempo estimation.
- Approximate pitch-class key estimation.
- A representative approximately 30-second window selected with chroma
  self-similarity.

Completed catalog rows reuse the cached window. Pending/failed catalog analysis
and Audius tracks use the whole clip.

### Stage 4: transition planning

The deterministic planner calculates a 1.5-8 second transition from BPM
difference, pitch-class distance, and the smoother-feedback flag. It does not
use a learned model. See
[`backend/app/services/pipeline/transition_planner.py`](backend/app/services/pipeline/transition_planner.py#L36).

### Stage 5: rendering

The renderer downloads at most 15 MiB per remote source, decodes audio with
pydub/ffmpeg, trims selected windows, and writes UUID-named WAV files under the
render volume. See
[`backend/app/services/pipeline/audio_renderer.py`](backend/app/services/pipeline/audio_renderer.py#L42).

For multiple segments it creates one composite file and applies the planned
crossfades. For one segment it only trims/exports that segment.

Consequently:

- Mix generation uses real multi-track crossfading.
- Live session resolution always invokes the renderer with one segment in
  [`backend/app/services/session_manager.py`](backend/app/services/session_manager.py#L307),
  so no live-session crossfade is currently audible.

## End-to-end feature flows

### Live session

1. The browser posts a prompt to `/sessions/start`.
2. Prompt understanding produces a guarded `PromptIntent`.
3. Audius/catalog retrieval returns candidates.
4. Recent track IDs and artists influence selection.
5. One segment is selected and rendered.
6. `DJSession` persists intent, playback data, reasoning, history, and trace.
7. The frontend plays the returned URL and reports native media state.
8. Feedback stores an immutable event, mutates relevant intent fields, and
   updates authenticated-user preferences.
9. Track completion automatically calls `/advance`.
10. The current Phase C work attempts to render and preload the next choice
    before completion.

Guest sessions are permitted. Authenticated sessions are owner-protected;
anonymous session UUIDs act as capability identifiers.

### Persisted mix

1. `/mixes/start` runs the same intent and retrieval stages.
2. Up to five tracks are selected.
3. Every segment and transition is planned together.
4. The renderer produces one composite WAV.
5. A `Mix` and ordered `MixSegment` rows are inserted transactionally.
6. Owners may edit and publish the draft.
7. Published mixes appear in feeds and profiles and support likes/saves.

### Catalog and attachment upload

Catalog uploads are authenticated multipart requests. The backend enforces a
streamed 10 MiB limit, checks content type and magic bytes, stores the file via
the shared priority queue, inserts a `CatalogTrack`, and queues analysis.

Generic forum/message attachments use raw or JSON batch upload endpoints. The
queue validates and stores bytes, the frontend polls the job, and the first
successful poll materializes the `Attachment` row. A later post, comment, or
message transaction claims that staged attachment.

### Community, social graph, and messages

- Community feeds support public, friends, and discussion modes.
- Discussions may be anonymous and require a title.
- Posts and comments support attachments and reversible `-1/+1` votes.
- Mixes can be shared as native playable posts.
- Friend requests become canonical ordered friendship rows on acceptance.
- Blocking removes friendships and pending requests.
- Direct messages require friendship and no bilateral block.
- Notifications persist in PostgreSQL and are also pushed over WebSockets.
- Community WebSockets send only a generic invalidation; clients reload via
  authorized REST requests.

### Listening and Music Identity

Players count actual forward-playing seconds rather than assuming a play-button
click equals listening. Events are sent on completion, skip, stop, change, or
component teardown.

The backend resolves track/artist/genre/vibe from the referenced session or mix
instead of trusting client metadata. It rejects impossible timestamps and
clamps duration to the stored segment.

Music Identity then derives artist, genre, vibe, track, time-of-day, trend,
discovery, and recent-context metrics. Privacy supports private, friends, and
public visibility. Listening DNA remains a stable but intentionally ungenerated
future-ML response.

## Persistence model

The relational model can be viewed in four groups:

### Identity

- `User`
- `Profile`
- `UserMusicProfile`
- `UserPreference`
- `PromptShortcut` (added post-review; see the addendum below)

### Music

- `DJSession`
- `SessionFeedback`
- `Mix`
- `MixSegment`
- `MixLike`
- `SavedMix`
- `CatalogTrack`

### Community and communication

- `ForumPost`
- `ForumComment`
- Post/comment vote tables
- `FriendRequest`
- `Friendship`
- `UserBlock`
- `SocialReport`
- `DirectMessage`
- `Notification`

### Media and analytics

- `Attachment`
- `ListeningEvent`

Core live-session state is stored as JSON inside `DJSession`: original/current
intent, now-playing data, reasoning, pipeline trace, recent tracks/artists, and
prepared-next data. This provides flexibility but lacks database-level schema
enforcement and makes historical migrations more fragile.

Alembic currently has one migration head, `fbb453a67fc8`, including the
uncommitted prepared-next migration.

## Realtime and background-processing model

The system deliberately uses lightweight process-local infrastructure:

- A bounded `PriorityQueue` and daemon threads for uploads/analysis.
- In-memory Audius and candidate caches.
- Sliding-window rate-limit dictionaries.
- In-memory WebSocket connection sets/maps.
- Per-session prefetch locks.

PostgreSQL notification rows and stored file bytes are durable. Queue jobs,
cache contents, rate-limit state, and WebSocket membership are not.

Production therefore defaults to one Uvicorn worker in
[`docker-compose.prod.yml`](docker-compose.prod.yml#L98). Redis or equivalent
shared queue/pub-sub/rate-limit infrastructure and shared object storage are
prerequisites for safe horizontal scaling.

## Deployment architecture

### Development

`docker-compose.yml` starts:

- PostgreSQL 16.
- A one-shot Alembic migration container.
- An upload-volume ownership initializer.
- One FastAPI backend.
- Nginx serving the built SPA and proxying `/api`.
- Ollama with a persistent model volume.
- Optional Adminer under the `tools` profile.

Host database, backend, and frontend ports bind to loopback.

### Production

`docker-compose.prod.yml` uses immutable backend/frontend image references,
internal PostgreSQL, backend, frontend, and Ollama services, and exposes only
Caddy on ports 80/443. Caddy manages TLS, strips `/api`, limits request bodies,
and adds security headers.

The CI workflow in
[`../.github/workflows/zonix-ci-cd.yml`](../.github/workflows/zonix-ci-cd.yml#L16)
runs:

- Alembic upgrade/check against PostgreSQL.
- Backend tests and an 80% coverage gate.
- Frontend type/component checks.
- Frontend unit tests, formatting, lint, and dependency audit.
- Production frontend build and Chromium smoke tests.
- Development and production Compose validation.
- Backend and frontend container builds.

Image publishing is enabled only when `DEPLOY_ENABLED=true`; Azure deployment
is separately gated by `VM_DEPLOY_ENABLED=true`. **Update, post-review:** both
are now `true` and the deployment is live -- see the addendum below and
[`deploy/README.md`](deploy/README.md#L1), which no longer describes this as
a template.

There is currently no render garbage collection, metrics, or alerts. Backup,
restore, rollback, and external uptime monitoring, listed as missing at the
time of this review, are addressed in the addendum below; render GC,
metrics, and alerts are not.

## Review findings

### Blocker: Phase C prefetch concurrency

The prepared result is validated only by an intent fingerprint and TTL. It is
not tied to the current/base track or an optimistic session revision.

A possible failure sequence is:

1. Prepare starts while track A is current.
2. Advance or feedback changes the live state to track B.
3. The older prepare finishes and commits a result calculated from A.
4. Its intent fingerprint still matches.
5. The next advance consumes the stale result, potentially replaying B and
   exposing transition reasoning based on the wrong previous track.

Prepare may similarly commit after stop because it checks status before the
slow network/render work. The per-session lock covers only prepare-versus-
prepare in one process, does not coordinate with advance/feedback/stop, never
refreshes a stale ORM row after lock acquisition, and grows indefinitely.

Other Phase C defects:

- `prepared_at` persists `time.monotonic()`. That timestamp is not portable
  across host reboot, database restore/migration, or another host/replica.
- Expired or fingerprint-mismatched JSON is ignored but not always cleared.
- The router reports `prepared=true` from non-nullness rather than fresh
  validity.
- Prepare, advance, and feedback share one frontend AbortController slot. An
  older request's unconditional `finally` can clear a newer request's
  controller in
  [`frontend/src/lib/stores/sessionStore.js`](frontend/src/lib/stores/sessionStore.js#L148).
- Every unused prefetch can leave a permanent rendered WAV.
- The current double-prepare test is sequential and does not test actual lock
  contention or prepare-versus-advance/feedback/stop.

Recommended correction:

- Add an optimistic session version and base-track key.
- Perform slow network/render work outside the database lock.
- Commit and consume only through atomic compare-and-swap conditions covering
  session ID, status, version, current track, and intent fingerprint.
- Persist an absolute UTC expiry.
- Give prefetch its own controller and clear shared controllers only by
  identity.
- Delete unused render artifacts transactionally or through lifecycle GC.

### High: unbounded guest and render growth

Anonymous callers may create persistent sessions and ownerless mix drafts.
Successful renders write new UUID WAV files in
[`backend/app/services/pipeline/audio_renderer.py`](backend/app/services/pipeline/audio_renderer.py#L90).

There is no quota or retention policy for guest sessions, guest mixes, catalog
tracks, or rendered files. Existing cleanup inspects files only directly under
`UPLOAD_DIR` and skips `renders/` and `catalog/` in
[`backend/app/cleanup_uploads.py`](backend/app/cleanup_uploads.py#L19).

Recommended correction:

- Require authentication for persistent generation, or make guest output
  explicitly ephemeral.
- Add per-user/IP quotas and request-cost limits.
- Add database and file TTL cleanup, disk monitoring, and lifecycle APIs.
- Remove ownerless drafts that cannot be published or retrieved normally.

### High: debug visibility

When pipeline debugging is enabled, any authenticated user can read the newest
20 sessions across all users, including prompts, user IDs, and traces in
[`backend/app/routers/debug.py`](backend/app/routers/debug.py#L47).

The feature needs an administrator/operator permission, owner filtering, or
network-level isolation rather than an ordinary login plus feature flag.

### High: historical migration safety

Migration `e7b3d2a91f44` adds required session-state JSON fields with empty-object
defaults but does not backfill valid current-session structures. Current
serialization assumes keys such as `audio_url`, `title`, and
`selectedMoment` exist.

A session created before that migration can therefore fail after upgrade. Add a
backfill or deliberately archive/delete incompatible active sessions, and test
an upgrade containing populated old rows.

### High: single-process scaling boundary

Upload jobs, search/candidate caches, rate limits, prefetch locks, notification
fanout, community invalidation, and pipeline-debug fanout are process-local.

Increasing `BACKEND_WORKERS` or adding replicas will split those states. The
current one-worker deployment is internally consistent, but safe scaling
requires shared job storage, pub/sub, rate limits, and object storage.

### Medium: frontend media lifecycle

There are two independent audio systems:

- The live DJ player is mounted only on `/`.
- The persisted-mix player is global.

They have no arbitration, so both can play simultaneously. Navigating away can
destroy live audio while `sessionStore` still reports a playing session;
returning can restart it. Logout resets neither media store, which risks stale
cross-account state and listening events.

Starting a replacement vibe also clears the visible old session before the new
request succeeds. The old backend session is stopped only after success, so a
failed replacement leaves it active while losing its ID from the UI. See
[`frontend/src/lib/stores/sessionStore.js`](frontend/src/lib/stores/sessionStore.js#L190).

Recommended correction: introduce one global media coordinator, keep the live
player mounted at layout level or explicitly stop it on navigation, and reset
both media stores on logout/account change.

### Medium: frontend request and realtime consistency

- Mix generation uses the generic 15-second API timeout even though session
  generation allows 45 seconds for the same expensive pipeline.
- Navbar and Messages open independent notification WebSockets and maintain
  separate unread state.
- Notification and Community sockets have no reconnect/backoff strategy.
- Open post comments are not refreshed by Community invalidations.
- Rapid message/profile/tab changes can apply stale responses because several
  page requests lack AbortController/version guards.
- Direct navigation to `community?tab=people` can race the initial auth check
  and never reload after authentication succeeds.
- Older messages, comments, and posts lack complete pagination UI.
- Staged post/message attachments are not consistently deleted when a page is
  abandoned.

### Medium: interaction and analytics integrity

- Mix like/save operations do not apply the same bilateral block policy as mix
  reads and messaging.
- A delayed listening event for a live session is resolved against whatever
  track is current when the request arrives, potentially misattributing it.
- Clients can fabricate listening duration up to the stored segment limit.
- Anonymous content hides the author in responses but still affects public
  profile counts, allowing low-volume timing/count correlation.
- Social reports accept records but have no review/status/admin workflow.

### Medium: request performance

High-volume reads contain N+1 patterns:

- Mix feed membership/count lookups per item.
- Forum author/vote/comment/attachment lookups per post.
- Sender/recipient/attachment lookups per message.
- Latest message, unread count, profile, and user lookups per friend.
- Repeated relationship/profile queries per user card.
- Music Identity loads events into Python and performs further context lookups.

Use grouped subqueries, eager loading, composite indexes, SQL aggregation, and
keyset pagination before production-sized datasets are introduced.

### Medium: blocking and expensive request work

Catalog upload is an async endpoint whose worker polling uses synchronous
`time.sleep`, blocking the event loop for up to five seconds.

The AI-DJ pipeline also performs serial provider searches, downloads, decoding,
and rendering inline in request threads. It has no dedicated pipeline job
queue, decoded-audio memory bound, circuit breaker, or output-duration quota.

### Configuration gaps

Several pipeline settings are read by Python but not passed by either Compose
backend environment, including `AUDIUS_RETRIEVER`, Audius API/cache/ranking
knobs, candidate-pool settings, and `PREPARED_NEXT_TTL_SECONDS`.

Compose `.env` files are interpolation sources; variables not listed in the
service environment are not automatically injected. The documented
single-variable multi-query/single-query rollback therefore does not work until
Compose is updated.

Production also starts and pulls `qwen3:8b` even when the LLM provider is
disabled, with no container CPU/memory limit or GPU configuration. On a small VM
this can compete with the API and rendering workload.

## Testing and validation

The following checks passed against the current working tree:

| Check | Result |
| --- | --- |
| Backend tests | 162 passed |
| Backend statement coverage | 88.16%, above the 80% gate |
| Frontend unit tests | 15 passed across 3 files |
| Svelte component/type check | 0 errors, 0 warnings |
| Prettier and ESLint | Passed |
| Production frontend build | Passed |
| Playwright Chromium smoke tests | 3 passed |
| Development Compose validation | Passed |
| Production Compose validation | Passed |
| Alembic heads | One head: `fbb453a67fc8` |

Warnings observed locally:

- Local ffmpeg was not available. Container and CI definitions install/check
  it, but compressed-media behavior was not fully representative locally.
- Starlette's current TestClient/httpx integration reports a deprecation
  warning.
- Pydub depends on Python's deprecated `audioop` module.

### Test-depth limitations

- Backend request tests replace the application database with in-memory SQLite
  in [`backend/tests/conftest.py`](backend/tests/conftest.py#L26).
- CI migrates a fresh PostgreSQL database, but application request/query tests
  do not run against PostgreSQL.
- Historical migrations are not tested against populated old data.
- Audius is normally mocked empty in backend tests.
- Playwright mocks the complete `/api/**` boundary in
  [`frontend/e2e/smoke.spec.js`](frontend/e2e/smoke.spec.js#L40).
- There are no concurrent-write, multi-worker, restart, load, accessibility,
  live-provider contract, end-to-end full-stack, or objective audio-quality
  tests.
- Frontend unit tests cover the API client, selected normalizers, and the new
  prefetch store behavior, but not the complete auth, realtime, upload, player,
  or route-mutation lifecycles.

## Documentation review

Documentation has significant drift:

- [`README.md`](README.md#L31) overstates live-session crossfading.
- [`ZONIX_PROJECT_README.md`](ZONIX_PROJECT_README.md#L10) and
  [`backend/BACKEND_README.md`](backend/BACKEND_README.md#L8) incorrectly say
  real rendering and audio analysis are not implemented.
- Pipeline documentation says there is no ranking stage even though the
  deterministic multi-query metadata ranker is implemented.
- Some pipeline documentation still describes catalog-first sessions, while
  current dependencies use Audius first.
- Several frontend historical guides describe authentication and audio as
  placeholders.
- Deployment documentation is clearer and correctly distinguishes a deployable
  template from a verified public deployment.

The source code is currently more accurate than any one document. The maintained
architecture should be consolidated into a single source of truth, while
historical snapshots should move under a clearly marked `docs/archive/`
directory.

## Recommended implementation order

1. Correct Phase C with optimistic session versioning, base-track validation,
   atomic compare-and-swap, UTC expiry, controller ownership, and concurrent
   tests.
2. Add quotas and lifecycle cleanup for guest sessions, ownerless mixes,
   generated renders, staged attachments, and catalog files.
3. Restrict pipeline debug access and repair migration, block-policy, and
   anonymity/privacy issues.
4. Introduce one frontend media coordinator and correct replacement-session,
   logout, timeout, cancellation, and WebSocket recovery behavior.
5. Replace process-local queues, rate limits, and pub/sub before increasing the
   backend worker or replica count.
6. Add PostgreSQL integration tests and full-stack browser tests against the
   real API.
7. Add populated migration tests, concurrency/load tests, accessibility tests,
   provider contracts, and audio-quality validation.
8. Add backup/restore automation, render GC, metrics, alerts, rollback, and
   external deployment verification.
9. Update Compose to expose every supported runtime setting.
10. Consolidate and archive documentation.

## Addendum: long-term memory verification and personalized shortcuts

Added after this review's original date, closing the "Long-term memory"
completion criterion this review's own findings did not yet cover:

- A labeled, offline evaluation
  ([`backend/scripts/eval_preferences.py`](backend/scripts/eval_preferences.py#L1))
  now verifies that a learned `UserPreference` measurably improves ranked
  candidate precision for a neutral prompt, regression-asserted on a fixed
  seed in
  [`backend/tests/test_preference_eval.py`](backend/tests/test_preference_eval.py#L1).
  The evaluation exposed that the pre-existing energy bias (mutating
  `PromptIntent.energy` via `_apply_preference` in
  [`backend/app/services/session_manager.py`](backend/app/services/session_manager.py#L158))
  rarely reached ranking at all: the old `energy_score` signal in
  [`backend/app/services/pipeline/audius_retriever.py`](backend/app/services/pipeline/audius_retriever.py#L194)
  only applied when a candidate had neither tag nor mood metadata, which
  most real Audius tracks do have. A new, independent `energy_alignment_score`
  signal (`WEIGHT_ENERGY_ALIGNMENT`) closes that gap.
- A logged-in user's own repeated *prompt intent* -- clustered by a
  normalized signature (mood/energy/vocals/genres/whether an artist was
  required), not exact text, via the existing deterministic
  [`prompt_parser.py`](backend/app/services/prompt_parser.py#L176) -- is now
  remembered in a new `prompt_shortcuts` table
  ([`backend/app/services/prompt_shortcuts.py`](backend/app/services/prompt_shortcuts.py#L1))
  and surfaced as personalized shortcut chips ahead of the static preset
  list, once a signature has recurred at least `PROMPT_SHORTCUT_MIN_USES`
  (default 3) times. Endpoint:
  `GET /users/me/prompt-shortcuts`
  ([`backend/app/routers/profiles.py`](backend/app/routers/profiles.py#L1)).
  Frontend integration:
  [`frontend/src/lib/components/PromptComposer.svelte`](frontend/src/lib/components/PromptComposer.svelte#L1)
  merges personalized chips ahead of `PRESETS` via
  [`frontend/src/lib/utils/shortcuts.js`](frontend/src/lib/utils/shortcuts.js#L1);
  guests never fetch or see personalized chips, since there's no identity to
  key off.

Neither change alters this review's other findings or its recommended
implementation order; they are additive, scoped to the "Long-term memory"
row of [`CUEMIX_PROJECT_README.md`](CUEMIX_PROJECT_README.md#L206)'s
Course-feedback status table.

## Addendum: deployment hardening (backup, restore, rollback, uptime)

Closes the CI/CD row of
[`CUEMIX_PROJECT_README.md`](CUEMIX_PROJECT_README.md#L211)'s
Course-feedback status table and the gap this review flagged above
("no automated rollback, PostgreSQL/upload backup, restore exercise, ...
or external uptime check"). The deployment is live at
`https://sweng-group-18.eastus.cloudapp.azure.com` (`VM_DEPLOY_ENABLED=true`),
auto-deployed from `main` on green CI.

- **Backup:** [`deploy/backup.sh`](deploy/backup.sh#L1), installed as a
  daily 03:00 UTC cron job by
  [`deploy/remote-deploy.sh`](deploy/remote-deploy.sh#L1) (idempotent, so
  every deploy refreshes it). `pg_dump`s the production database and
  archives the `cuemix-production_uploads_data` volume to a
  retained-on-VM, timestamped directory (`~/cuemix-backups`), pruning
  entries older than 14 days. Off-VM (object store) replication is not yet
  implemented -- a disk/VM failure would still lose both the live data and
  its backups.
- **Restore:** [`deploy/restore.sh`](deploy/restore.sh#L1) restores a
  `backup.sh` archive into either the live production database/volume or a
  named scratch database/volume alongside it.
  [`deploy/backup-restore-drill.sh`](deploy/backup-restore-drill.sh#L1),
  wired to the `backup-restore-drill` `workflow_dispatch` job in
  [`.github/workflows/cuemix-ci-cd.yml`](.github/workflows/cuemix-ci-cd.yml#L440),
  runs the whole backup -> restore-into-scratch -> verify -> cleanup cycle
  over one SSH connection the runner holds only for the job's lifetime, so
  no human or external agent needs the production SSH key just to verify
  backups still restore correctly.
  **Drill performed:** via that job on 2026-08-15 (run ID `31899351678`).
  Backed up production (`db-20260815T174839Z.sql.gz` /
  `uploads-20260815T174839Z.tar.gz`), restored into scratch database
  `cuemix_restore_drill_31899351678` and scratch volume
  `cuemix-restore-drill-31899351678_uploads_data`, and confirmed an exact
  match against production at the time -- **12/12 database rows** across 26
  tables (`dj_sessions`: 4, `catalog_tracks`: 4, `session_feedback`: 2,
  `known_broken_tracks`: 1, `alembic_version`: 1, the rest 0) and **9/9
  uploaded files**. Scratch resources were dropped automatically on exit;
  production was never written to. One bug was caught and fixed by this
  drill's first (failing) run: `docker compose exec` against `postgres`
  still requires `BACKEND_IMAGE`/`FRONTEND_IMAGE` to be set, since Compose
  interpolates the entire file (including the unrelated
  `migrate`/`backend`/`frontend` services) before running any subcommand --
  `backup.sh`/`restore.sh`/`backup-restore-drill.sh` now export harmless
  placeholders for both.
- **Rollback:** every image is already tagged by commit SHA
  (`ghcr.io/<owner>/cuemix-backend:<sha>`); a `workflow_dispatch` input
  (`rollback_sha`) on the `rollback-production` job in
  [`.github/workflows/cuemix-ci-cd.yml`](.github/workflows/cuemix-ci-cd.yml#L332)
  redeploys that SHA's already-published images via
  `deploy/remote-deploy.sh` with no rebuild, using that SHA's own
  Compose/Caddy/deploy-script definitions.
  **Drill performed:** live on 2026-08-15, rolling back to
  `10ef342609eb59cb8f374d7425203f076d9aacf8`. Confirmed via `docker ps` on
  the VM that both `cuemix-production-backend-1` and
  `cuemix-production-frontend-1` were running images tagged with that SHA,
  and the job's own health-endpoint check passed. Rolled forward again
  afterward. This drill caught a second real bug: the workflow's
  `concurrency.group` was keyed only by `github.ref`, which is
  `refs/heads/main` for both an ordinary push to `main` *and* a
  `workflow_dispatch` run launched against `main` -- with
  `cancel-in-progress: true`, a rollback/drill dispatch could (and did)
  silently cancel an in-flight push's own test/build/publish/deploy job
  before its images ever published, which is why the first "roll forward
  to latest" attempt failed with "not found." `workflow_dispatch` runs now
  get their own concurrency group, keyed by `run_id`.
- **External uptime check:**
  [`.github/workflows/uptime-check.yml`](.github/workflows/uptime-check.yml#L1)
  curls `$PUBLIC_BASE_URL/api/db-health` every 15 minutes and opens/updates
  a GitHub issue labeled `uptime` on failure, closing it automatically on
  recovery. A GitHub Actions workflow rather than a third-party monitor
  (UptimeRobot/Better Uptime) -- no external account to provision, at the
  cost of checking from GitHub's own infrastructure rather than truly
  outside it, and GitHub's scheduled-run queuing delay under load (roughly
  "noticed within half an hour," not a tight SLA).
- **Branch/environment protection:** <!-- BRANCH_PROTECTION_VERIFIED -->

Render garbage collection, metrics, and alerts (beyond the uptime check
above) remain open, matching this review's original "High: unbounded guest
and render growth" finding and recommended implementation order.

## Final assessment

Zonix is a strong and genuinely functional prototype with good modular
boundaries, broad feature coverage, solid backend tests, careful input
validation, and a credible container/CI story.

Its next milestone should be correctness and operational hardening rather than
additional feature breadth. Stabilizing the current prefetch work, bounding
permanent storage, protecting operator data, unifying media ownership, and
replacing process-local coordination will produce the largest improvement in
reliability and production readiness.
