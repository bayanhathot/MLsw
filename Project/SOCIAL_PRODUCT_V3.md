# Cuemix Social Music Infrastructure — V3

This version reshapes Cuemix around one product loop instead of separate profile, forum, messaging, and mix islands:

```text
listen -> Music Identity -> publish/share music -> friends react ->
community/messages -> discover more music -> listen again
```

The AI/ML DJ models are intentionally **not** part of this iteration. The goal here is production-oriented full-stack infrastructure and a coherent music-first social experience.

## Product navigation

Desktop navigation is now centered on four primary destinations:

- **DJ** — prompt-guided listening
- **Discover** — published mixes
- **Community** — Friends / Explore / Discussions / People
- **Library** — owned and saved mixes

Search, notifications, messages, and the current-user avatar live as utility actions in the navbar rather than separate primary destinations.

Legacy `/forum` and `/social` URLs remain as compatibility redirects to Community/Discussions and Messages.

## Social graph

New persistent data:

- `friend_requests`
- `friendships`
- `user_blocks`
- `social_reports`

Friend relationships are mutual. Requests support pending, accepted, declined, and cancelled states. Friendship pairs are normalized and unique so the same relationship cannot exist twice.

Core APIs include:

```text
GET    /users/search?q=...
GET    /users/discover
GET    /friends
GET    /friends/requests
POST   /friends/requests/{username}
DELETE /friends/requests/{username}
POST   /friends/requests/{id}/accept
POST   /friends/requests/{id}/decline
DELETE /friends/{username}
POST   /users/{username}/block
DELETE /users/{username}/block
POST   /reports
```

Direct messages are friends-only by default. Blocking prevents relationship and messaging interactions between the two users.

## Public profiles

`/users/[username]` is now a social-first profile rather than a full analytics report.

It provides:

- profile identity and music interests
- friendship state and actions
- Message action for friends
- published mix count and public mixes
- friends and mutual-friend context
- Music Identity snapshot
- tabs for Overview, Music Identity, Mixes, Activity, and Friends
- block/report controls

Detailed analytics remain available under the Music Identity tab.

## Music Identity analytics

Music Identity remains factual infrastructure built from raw `listening_events`; no Listening DNA model is fabricated.

All dashboard metrics now share a requested time period:

- 7 days
- 30 days
- 6 months
- all time

The API supports:

```text
GET /users/me/music-identity?period=30d
GET /users/{username}/music-identity?period=30d
```

Current factual metrics include:

- total actual listening time
- top artist and artist distribution
- top genre and genre distribution
- top vibe and vibe distribution
- top tracks
- artists heard / tracks heard
- listening context count and average context duration
- time-of-day distribution
- listening trend
- recent listening contexts

The Listening DNA response contract remains present with `status=not_generated` until future algorithms are implemented.

## Music Identity privacy

Privacy is now three-state rather than only public/private:

- `private` — owner only
- `friends` — accepted friends and owner
- `public` — everyone

The backend enforces visibility before analytics are returned. The legacy `is_public` field remains only for backward compatibility and is synchronized with the new visibility field.

## Community

The old generic forum is now presented as **Community** with four product modes:

- **Friends** — posts from the current user and accepted friends
- **Explore** — public social/music posts
- **Discussions** — existing forum-style discussions with optional anonymity and up/down voting
- **People** — user search, discovery, friend requests, and current friends

The existing forum capabilities are preserved for course requirements, but the main social feed uses simpler social interactions.

### Native music sharing

Forum/community posts now support:

```text
kind = discussion | status | mix_share
visibility = public | friends
mix_id = optional published mix
```

Published mixes can be shared directly from a Mix card with a caption and visibility. Shared mixes render as native playable cards inside Community rather than as pasted URLs.

Anonymous posting and up/down voting remain focused on Discussions. Status and mix-share posts use a simple Like / Comment / Share interaction model in the UI.

## Messages and notifications

The previous manual "type a username and load history" messaging surface has been replaced with a conversation-oriented inbox.

`GET /conversations` returns conversation summaries including the last message and unread state. Messages remain durable in PostgreSQL and use the existing WebSocket path for live delivery.

Notifications are now surfaced directly in the navbar with unread badges. Friend-request/acceptance and mix-like events create durable notifications and also push live updates.

## Persistent global player

A global player store and `GlobalPlayer.svelte` are mounted at the app layout level. Mix playback can continue while the user navigates between Discover, Community, Library, and profiles.

This is important for a music-first social product: navigation no longer inherently ends the listening experience.

## Safety and moderation infrastructure

V3 adds infrastructure for:

- blocking users
- reporting users/posts/comments
- preventing blocked-user feed/profile/message interactions
- friends-only DMs

A full moderation review/admin console is intentionally deferred.

## Realtime community behavior

Community feed changes are broadcast through a lightweight process-local WebSocket hub. The event is intentionally generic (`feed_changed`); clients then reload through authorized REST endpoints, avoiding accidental leakage of friends-only/private post content over the socket.

This is suitable for the current single-process deployment. Before running multiple backend workers, move realtime fan-out, queue coordination, and shared rate-limit state to Redis or another shared service.

## What is intentionally deferred

This infrastructure version does **not** implement:

- Listening DNA generation
- user/music embeddings
- friend or content recommendation ML
- AI feed ranking
- DJ transition/segment-selection models
- actual audio crossfade intelligence
- collaborative mixes
- follower/creator graph
- moderation admin console

Those can be added later without changing the core profile/social contracts built here.

## Scaling backlog

The next infrastructure optimizations, when scale requires them, are:

1. batch eager-loading/aggregation to remove N+1 feed queries
2. SQL `GROUP BY` analytics rather than loading large listening histories into Python
3. Redis/pub-sub for WebSockets, queues, and multi-worker state
4. cursor pagination for high-volume Community and conversation feeds
5. moderation workflow and audit tooling
6. accessible keyboard/focus testing and broader live E2E coverage

## Debugging the social product

Debug bottom-up:

```text
PostgreSQL -> Alembic -> FastAPI -> REST/WebSocket -> Svelte state -> UI
```

Useful checks:

```powershell
docker compose up --build
docker compose ps -a
docker compose logs -f backend
```

Then use `/api/docs` to verify friend/profile/community endpoints independently from the frontend.

For a friendship test, use two accounts:

1. User A searches for User B.
2. A sends a friend request.
3. B sees the request under Community -> People and accepts it.
4. Both profiles now show Friends.
5. DMs work between A and B.
6. A posts a Friends-only status; B can see it in Friends, a non-friend cannot.
7. Set A's Music Identity visibility to Friends; B can view it, a non-friend cannot.
8. Block B from A and verify messaging/social access is denied appropriately.

For native mix sharing:

1. publish a mix
2. click Share
3. add a caption and choose Everyone or Friends
4. confirm the Community post contains a playable mix card
5. navigate away while playing and confirm the global player persists
