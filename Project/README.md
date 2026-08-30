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

Compose seeds a realistic ~50-listener dataset -- accounts, profiles, a
social graph, forum posts/comments/votes, direct messages, mixes, DJ
sessions, and listening history (`app/coldseed/build.py`) -- automatically
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
| CueMix Studio: waveform-assisted exact saved moments, manual timeline, transition preview, render/publish, saved-segment auto-mix | Implemented locally |
| Studio AI assistant | Implemented as an isolated, internal, fail-open service sharing Ollama + Redis; recommendations require user confirmation |
| Community: Friends/Explore/Discussions/People, posts/comments/votes, mix sharing, attachments | Implemented |
| Public profiles, mutual friends, friend-only DMs, live/durable notifications, block/report | Implemented |
| Music Identity analytics (listening statistics, most-replayed segment, average segment length, time saved, period filters, visibility controls) | Implemented; a "Listening DNA" ML feature is a stable but deliberately unimplemented contract |
| Trained ranking/recommendation model | Deliberately not implemented |
| LLM prompt refinement | Implemented; local Ollama (sole option) or off (`VIBE_LLM_PROVIDER=none`). Verified 2026-08-15 against the live Azure VM (`qwen3:8b`): Concurrency (bounded admission, never blocks/crashes under load) — 20 concurrent callers vs. a limit of 4 → high-water-mark 4/4, 0 failures. Performance (multi-turn math + context retention) — PASS, exact 6.7% tempo-increase answer, both check types passed; see [backend/README.md#evaluations](backend/README.md#evaluations) for the full transcript and a caveat about production's shorter timeout. |
| CI | Every push/PR runs backend tests (80% coverage gate), frontend checks/tests/e2e, and container builds |
| Azure CD | Live at `https://sweng-group-18.eastus.cloudapp.azure.com`; auto-deploys `main` on green CI — see [deploy/README.md](deploy/README.md) |

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

Audius moments can be saved, arranged, previewed, and privately rendered, but
provider audio cannot be republished as a CueMix-owned public asset. Public
publishing is limited to the user's uploads and bundled demo tracks. Auto-mix
uses saved moments, named modes, and bounded/decayed behavioral signals, and
always returns an ordinary editable draft.

`studio-ai-service` is reachable only by the backend over the Compose network.
It shares the existing Ollama model and Redis concurrency controls, receives a
bounded authoritative context, and returns schema-constrained suggestions; it
has no database access and never mutates a draft. If it or Ollama is down, the
chat reports unavailable while every manual Studio feature keeps working.

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

The ordinary Playwright command runs the production frontend against
controlled API fixtures. GitHub Actions also provisions a real PostgreSQL,
Redis, FastAPI, and production frontend stack and runs
`realtime-integration.spec.js`, `profile-integration.spec.js`, and
`memory-integration.spec.js`. That real suite covers the complete coaching
memory journey (register, start a DJ session, coach, sign out/in, and verify
the remembered intent in a later session). Container builds, image publishing,
and Azure deployment wait for both the ordinary checks and this real-backend
suite to pass.

To point those real integration files at an already-running stack manually,
set `PLAYWRIGHT_BASE_URL` to its frontend origin and
`PLAYWRIGHT_BACKEND_URL` to its backend API origin before invoking Playwright.
The CI workflow supplies both automatically and uses an ephemeral test
database, so CI runs do not modify production data.

Do not commit `.env`, virtual environments, `node_modules`, model downloads,
or unlicensed audio. Runtime demo playback uses an original, procedurally
generated `cuemix-demo.wav` (see [backend/app/static/audio/GENERATED_AUDIO.md](backend/app/static/audio/GENERATED_AUDIO.md))
— no third-party sample.
