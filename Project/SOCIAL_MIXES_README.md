# Zonix Social Mixes — Teammate Handoff

This document describes the social mix feature added to Zonix. It covers the database design, backend API, frontend pages, migration workflow, testing steps, and the remaining integration work.

## 1. Feature overview

The new feature lets registered users:

- Generate an Audius-based mix and store it as a private draft.
- View their drafts and published mixes.
- Edit a draft's title, description, and cover URL.
- Publish a draft to the community feed.
- Browse published mixes.
- Play the first or selected stored segment in the frontend players.
- Like and unlike published mixes.
- Save and unsave published mixes as private bookmarks.
- View saved mixes in their personal library.

The intended flow is:

```text
Generate mix
→ Store mix and segments as a private draft
→ Edit it in My mixes (optional)
→ Publish it
→ Display it in the community feed
→ Other users can play, like, or save it
```

Authentication already existed before this feature. The social endpoints reuse the existing HTTP-only JWT cookie and `get_current_user` FastAPI dependency.

## 2. Important current limitation

The homepage still uses the older demo session flow:

```http
POST /sessions/start
```

That endpoint plays the hardcoded demo MP3 and does **not** create a database mix.

The new persistent social flow uses:

```http
POST /mixes/start
```

Until the homepage/player is migrated to `/mixes/start`, create test mixes through FastAPI Swagger at `http://localhost:5000/docs`. The draft will then appear under `/library`.

Do not call both start endpoints for one user action. They currently produce unrelated results: the sessions endpoint returns the demo file, while the mixes endpoint creates an Audius segment plan.

## 3. Database design

The social feature adds four PostgreSQL tables.

### `mixes`

Stores one generated mix and its publishing state.

```text
id
owner_id          → users.id
title
prompt
description
cover_url
status            → draft | published
created_at
published_at
```

Every mix belongs to one registered user. New mixes begin as `draft`; only `published` mixes appear in the feed.

### `mix_segments`

Stores the ordered playable parts of a mix.

```text
id
mix_id            → mixes.id
position
title
artist
audio_url
cover_url
start_second
end_second
transition_to_next
source
source_track_id
```

The `(mix_id, position)` pair is unique, so a mix cannot contain two segments at the same position.

The current MVP turns every Audius result into one segment from second 0 to at most second 45. It stores a mix plan, not a final combined MP3.

### `mix_likes`

Stores public likes.

```text
id
user_id            → users.id
mix_id             → mixes.id
created_at
UNIQUE(user_id, mix_id)
```

The unique constraint prevents one user from liking the same mix multiple times.

### `saved_mixes`

Stores private bookmarks.

```text
id
user_id            → users.id
mix_id             → mixes.id
created_at
UNIQUE(user_id, mix_id)
```

A save is different from a like: saves are private library bookmarks and do not affect the public like count.

Foreign keys use `ON DELETE CASCADE`, so deleting a user or mix removes dependent segments, likes, and saves.

## 4. Database and model files

Added:

```text
backend/app/database/models/mix.py
backend/app/database/models/mix_segment.py
backend/app/database/models/mix_like.py
backend/app/database/models/saved_mix.py
```

Updated:

```text
backend/app/database/models/user.py
backend/app/database/models/__init__.py
```

The `User` and `Mix` models now have a two-way SQLAlchemy relationship:

```python
mix.owner
user.mixes
```

The model package imports every model so Alembic can discover all tables.

## 5. Alembic migration

The generated migration is:

```text
backend/alembic/versions/f3dc072dcac2_add_social_mixes.py
```

It follows the original users migration:

```text
92efbb2c2a49_create_users_table.py
→ f3dc072dcac2_add_social_mixes.py
```

The migration creates all four social tables, their indexes, foreign keys, and unique constraints.

### Running Alembic through Docker

The current backend Dockerfile does not copy `alembic.ini` or the `alembic/` directory into the image. Mount the local backend directory into a temporary backend container.

From the project root:

```powershell
docker compose up -d postgres
docker compose build backend
```

Apply all migrations:

```powershell
docker compose run --rm --env DATABASE_URL_LOCAL= --volume "${PWD}\backend:/app" backend python -m alembic upgrade head
```

Check the active revision:

```powershell
docker compose run --rm --env DATABASE_URL_LOCAL= --volume "${PWD}\backend:/app" backend python -m alembic current
```

`DATABASE_URL_LOCAL` must be cleared inside Docker. Local development uses `localhost`, but containers reach PostgreSQL through the Compose service hostname `postgres`.

For future model changes, first ensure the database is current, then generate and apply a migration:

```powershell
docker compose run --rm --env DATABASE_URL_LOCAL= --volume "${PWD}\backend:/app" backend python -m alembic upgrade head

docker compose run --rm --env DATABASE_URL_LOCAL= --volume "${PWD}\backend:/app" backend python -m alembic revision --autogenerate -m "describe the change"

docker compose run --rm --env DATABASE_URL_LOCAL= --volume "${PWD}\backend:/app" backend python -m alembic upgrade head
```

Always review an autogenerated migration before applying it.

## 6. API schemas

Updated:

```text
backend/app/schemas.py
```

Added schemas:

- `MixSegmentRead`: serialized segment information.
- `MixOwnerRead`: safe public owner fields (`id` and `username` only).
- `MixUpdate`: editable mix metadata.
- `MixRead`: a complete stored mix with segments.
- `MixFeedItem`: a community feed item with owner and social state.

`MixFeedItem` includes:

```text
id
title
prompt
description
cover_url
owner
like_count
is_liked
is_saved
published_at
segments
```

`is_liked` and `is_saved` are calculated for the currently logged-in user. `like_count` is calculated from `mix_likes`; it is not stored as a counter on `mixes`.

## 7. Backend routes

The social API is implemented in:

```text
backend/app/routers/mixes.py
```

The router is registered by `backend/app/main.py` under the `/mixes` prefix.

### Generate and store a draft

```http
POST /mixes/start
```

Requires authentication. It:

1. Receives a prompt.
2. Searches Audius for up to five tracks.
3. Creates a `mixes` row with `status="draft"`.
4. Flushes the insert to obtain the database mix ID.
5. Creates ordered `mix_segments` rows.
6. Commits the mix and segments together.
7. Returns `MixRead`.

### Current user's mixes

```http
GET /mixes/mine
```

Returns the logged-in user's drafts and published mixes, newest first.

### Edit a mix

```http
PATCH /mixes/{mix_id}
```

Only the owner may edit the title, description, and cover URL. It does not edit segments or audio.

### Publish a mix

```http
POST /mixes/{mix_id}/publish
```

Only the owner may publish. It changes the status to `published` and sets `published_at`. Repeated publish requests do not reset the original publication time.

### Community feed

```http
GET /mixes/feed?limit=20&offset=0
```

Requires authentication in the current MVP. It returns published mixes newest first, including:

- Safe owner information.
- Total like count.
- Whether the current user liked the mix.
- Whether the current user saved the mix.
- Stored segments for playback.

Pagination validation:

```text
limit:  1–50, default 20
offset: 0 or greater, default 0
```

The current MVP performs extra queries per feed item to calculate social state. This is acceptable for small pages but should later be optimized with joins/subqueries.

### Like and unlike

```http
PUT    /mixes/{mix_id}/like
DELETE /mixes/{mix_id}/like
```

Only published mixes may be liked. `PUT` is idempotent and cannot create duplicate likes. `DELETE` removes only the current user's like. “Unlike” is not a negative downvote.

### Save and unsave

```http
PUT    /mixes/{mix_id}/save
DELETE /mixes/{mix_id}/save
```

Only published mixes may be saved. Saving creates a private bookmark; unsaving removes only the current user's bookmark.

### Saved library

```http
GET /mixes/saved
```

Returns the logged-in user's saved published mixes, ordered by the time they were saved.

## 8. Frontend API service

Added:

```text
frontend/src/lib/services/mixApi.js
```

It uses the existing shared `apiRequest` helper, which sends the HTTP-only authentication cookie with `credentials: "include"`.

Exported functions:

```text
generateMix(prompt)
updateMix(mixId, data)
publishMix(mixId)
getFeed({ limit, offset })
getMyMixes()
likeMix(mixId)
unlikeMix(mixId)
saveMix(mixId)
unsaveMix(mixId)
getSavedMixes()
```

## 9. Community feed frontend

Added:

```text
frontend/src/lib/components/MixCard.svelte
frontend/src/routes/feed/+page.svelte
```

`MixCard.svelte` displays:

- Cover image or Zonix placeholder.
- Owner username.
- Mix title, prompt, and optional description.
- Play button.
- Like/unlike button and count.
- Save/unsave button.

The feed page:

- Loads `/mixes/feed` on mount.
- Shows loading, empty, and error states.
- Renders a `MixCard` for each result.
- Plays the first stored segment in a fixed audio player.
- Uses optimistic UI for likes and saves.

Optimistic UI updates the button immediately. If the API request fails, the previous state is restored. Like counts use `Math.max(0, ...)` so the displayed value cannot become negative.

## 10. Personal library frontend

Added:

```text
frontend/src/routes/library/+page.svelte
```

The library requires authentication and redirects guests to `/login`.

It provides two tabs:

### My mixes

- Loads `/mixes/mine`.
- Shows Draft or Published status.
- Allows draft metadata editing.
- Publishes drafts with the Post mix button.
- Plays stored segments.

### Saved mixes

- Loads `/mixes/saved`.
- Plays saved mixes.
- Removes bookmarks with Remove saved.

The library has its own simpler card layout because `/mixes/mine` and `/mixes/saved` return `MixRead`, while the community card expects the richer `MixFeedItem` shape.

## 11. Running the project

From the project root:

```powershell
docker compose up --build
```

Open:

```text
Frontend:     http://localhost:8080
Backend docs: http://localhost:5000/docs
Adminer:      http://localhost:8081
```

Adminer connection values come from `.env`. When connecting from Adminer, use `postgres` as the server hostname, not `localhost`.

## 12. Manual end-to-end test

Because the homepage still uses the old session endpoint, use Swagger for mix generation.

### User A: create and publish

1. Register and log in as User A through the frontend.
2. Open `http://localhost:5000/docs` in the same browser.
3. Call `POST /mixes/start` with:

   ```json
   {
     "prompt": "chill electronic focus"
   }
   ```

4. Open `http://localhost:8080/library`.
5. Confirm the mix appears in My mixes as Draft.
6. Optionally edit its title, description, or cover.
7. Click Post mix.
8. Open `http://localhost:8080/feed` and confirm it appears.

### User B: like and save

1. Use another browser profile/incognito session.
2. Register and log in as User B.
3. Open `/feed`.
4. Like User A's mix and confirm the count changes.
5. Save the mix.
6. Open `/library` → Saved mixes and confirm it appears.
7. Unlike it and confirm the count decreases.
8. Remove it from Saved mixes and confirm the bookmark disappears.

### Security cases

Verify that:

- Guests receive `401` for protected mix endpoints.
- A user cannot edit or publish another user's mix.
- Drafts do not appear in the feed.
- Repeating Like does not create duplicate rows.
- Repeating Save does not create duplicate rows.
- Unliking or unsaving an already-absent relationship succeeds safely.

## 13. Files changed or added

### Backend

```text
backend/app/database/models/mix.py                         added
backend/app/database/models/mix_segment.py                 added
backend/app/database/models/mix_like.py                    added
backend/app/database/models/saved_mix.py                   added
backend/app/database/models/user.py                        updated
backend/app/database/models/__init__.py                    updated
backend/app/schemas.py                                     updated
backend/app/routers/mixes.py                               expanded
backend/alembic/versions/f3dc072dcac2_add_social_mixes.py  added
```

### Frontend

```text
frontend/src/lib/services/mixApi.js              added
frontend/src/lib/components/MixCard.svelte       added
frontend/src/routes/feed/+page.svelte            added
frontend/src/routes/library/+page.svelte         added
```

## 14. Remaining work

### Required integration

- Migrate the homepage from `/sessions/start` to `/mixes/start`.
- Adapt `sessionStore.js` and `DJPlayerCard.svelte` to the mix response shape.
- Decide whether the homepage requires login or supports anonymous temporary mixes.

### Audio/player work

- Play all segments in order instead of only the first segment.
- Advance automatically when a segment ends.
- Apply segment start/end boundaries.
- Add real crossfades and transitions.
- Refresh Audius playback URLs if they are temporary.

### Product/API work

- Add a dedicated `GET /mixes/{mix_id}` endpoint if feed payloads should become smaller.
- Decide whether guests may view the feed using optional authentication.
- Add Community and Library links to the navbar if they are not present.
- Add delete/unpublish behavior if needed.
- Confirm music-source licensing and attribution requirements for public sharing.

### Quality work

- Add pytest coverage for ownership, drafts, publishing, likes, saves, and duplicate prevention.
- Add frontend tests for optimistic UI rollback.
- Optimize feed social queries when data volume grows.
- Add consistent API response schemas for like/save operations.
- Update the older project README, which still describes sessions as in-memory and authentication as unfinished.

## 15. Recommended next milestone

The next milestone should be:

```text
Logged-in user starts a mix from the homepage
→ /mixes/start stores it as a draft
→ the player plays the generated segment queue
→ the same mix appears automatically in My mixes
```

Until that integration is implemented, the backend social system, feed, and library can be tested independently using Swagger-generated mixes.
