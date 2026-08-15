# Cuemix Music Identity

This repository now contains the full-stack infrastructure for the Music Identity feature. The analytics are factual aggregations from real playback events; the future Listening DNA algorithm is intentionally not implemented yet.

## Data flow

```text
Authenticated playback
  -> POST /listening-events
  -> listening_events (raw behavioral data)
  -> music_identity_service.py (deterministic aggregation)
  -> GET /users/me/music-identity
  -> Svelte Music Identity dashboard
  -> optional public profile when the owner enables it
```

The raw-event layer is deliberate: top artists, genres and future ML features can be recomputed without losing the original listening behavior.

## Implemented analytics

- actual recorded listening time (not full track duration)
- top artist and listening time per artist
- artist share of measured listening
- top genre and genre distribution where source metadata exists
- top vibe and recurring vibe distribution
- listening trend over time
- recent recorded mix / AI-DJ listening contexts
- a stable `listening_dna` API contract for future algorithms

No fake DNA label or feature values are generated. Until future ML exists the UI shows a designed "still taking shape" state.

## Privacy

Every `user_music_profiles` row starts with `visibility = "private"`. The legacy `is_public` flag remains synchronized for backward compatibility.

The owner can change this with:

```http
PATCH /users/me/music-identity/privacy
Content-Type: application/json

{"visibility": "friends"}
```

Public lookup is server enforced:

```http
GET /users/{username}/music-identity
```

Visibility is server-enforced: `private` is owner-only, `friends` is visible to accepted friends, and `public` is visible to everyone. When the viewer is not authorized, the response contains only safe public/profile visibility information and no analytics.

## New/extended database data

`user_music_profiles`
- privacy setting
- future DNA status / label / summary / feature JSON / version

`listening_events`
- idempotent client event ID
- authenticated user
- session or mix/segment context
- server-resolved source track metadata
- artist, genre and vibe when known
- start/end timestamps
- actual listened seconds
- completion ratio
- skipped flag

`mix_segments`
- genre
- vibe

The Alembic migration is:

`backend/alembic/versions/c8a8f71d2b40_add_music_identity_analytics.py`

## Playback event strategy

The players accumulate forward media-time deltas locally. They do **not** send one request per second. An event is flushed on meaningful boundaries such as:

- natural segment completion
- previous/next skip
- player close/stop
- track/session change
- media error
- component teardown (best-effort keepalive)

Seek jumps are excluded from listened-time accumulation. Backend metadata is resolved from the known Cuemix session/mix context, so a client cannot claim an arbitrary artist/genre for its profile.

## Frontend routes

- `/profile` — private owner dashboard and Music Identity controls
- `/users/[username]` — safe public profile
- `/community` — Friends / Explore / Discussions / People; author/comment names link to public profiles
- `/forum` — compatibility redirect to Community -> Discussions

Main profile components live in:

`frontend/src/lib/components/profile/`

## Future Listening DNA integration

The stable frontend/API contract is already present. Future ML should write/update the fields on `UserMusicProfile` and/or be called from:

`backend/app/services/music_identity_service.py`

The current response shape is conceptually:

```json
{
  "status": "not_generated",
  "label": null,
  "summary": null,
  "dimensions": [],
  "version": null
}
```

A future model can return dimensions such as energy, discovery, smoothness, vocals or genre diversity without requiring a dashboard rewrite.

## Debugging Music Identity step by step

Start at the bottom of the stack and move upward.

### 1. Verify migrations

```powershell
cd backend
python -m alembic upgrade head
python -m alembic check
```

With Docker:

```powershell
docker compose up --build
docker compose ps -a
docker compose logs migrate
```

The migration service should exit with code 0.

### 2. Verify raw events

Sign in, play an Audius mix segment for several seconds, then skip/finish it. Inspect PostgreSQL:

```sql
SELECT id, user_id, mix_id, segment_id, artist_name, genre, vibe,
       seconds_listened, completion_ratio, skipped, started_at
FROM listening_events
ORDER BY id DESC;
```

If no row appears, inspect browser DevTools -> Network for `POST /api/listening-events`, then inspect backend logs:

```powershell
docker compose logs -f backend
```

### 3. Verify analytics before debugging the UI

Open Swagger at `/api/docs` or request:

```http
GET /users/me/music-identity
```

Confirm the API totals agree with the rows in `listening_events`. Only after the JSON is correct should you debug the Svelte chart/card.

### 4. Verify privacy with two users

For user A, leave Music Identity private and request:

```http
GET /users/user-a/music-identity
```

as/without user B. It must not contain analytics. Then user A makes it public and the endpoint should return the dashboard data. Switch it to Friends and verify an accepted friend can access it while a non-friend cannot. Then switch it to Private and verify only the owner can access it.

### 5. Verify public profile links

Create a non-anonymous forum post/comment. Clicking its username should open `/users/<username>`.

## Verification performed for this implementation

Backend (latest V3 verification):

- `51 passed`
- coverage: `85.99%` (80% gate passed)
- Python compile check passed
- fresh Alembic upgrade through the new migration passed
- `alembic check`: no new upgrade operations detected

Frontend source:

- TypeScript/JSDoc `tsc --noEmit` passed
- all 32 Svelte source files compiled directly with the Svelte compiler

The uploaded archive contained Windows-native `node_modules`, while the implementation environment was Linux and offline. Therefore the normal Vite/SvelteKit `npm run check/build` could not be independently reinstalled/re-run here because the Linux optional native Rolldown binding was absent. On your Windows machine, delete copied `node_modules`, run `npm ci`, then run the normal frontend checks below.

```powershell
cd frontend
npm ci
npm run check
npm test
npm run lint
npm run build
npx playwright install chromium
npm run test:e2e
```
