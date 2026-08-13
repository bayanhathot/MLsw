# Zonix V3 Implementation Report

> **Point-in-time snapshot.** Written when the V3 social/community features
> first shipped; test counts and coverage figures below are from that run,
> not the current state. See [SOCIAL_PRODUCT_V3.md](SOCIAL_PRODUCT_V3.md)
> for the maintained architecture reference.

## Goal

Move Zonix closer to a coherent music-social product while deliberately postponing ML/AI model development.

## Major backend additions

- mutual friend requests and friendships
- user search/discovery
- block/report infrastructure
- friend-aware public profiles
- published mixes on profiles
- friends-only DMs and conversation summaries
- three-state Music Identity visibility
- consistent-period Music Identity analytics
- top tracks / time-of-day / discovery/context metrics
- Community post kinds and visibility
- native mix-share posts
- friends/explore/discussion feed modes
- process-local Community WebSocket invalidation hub
- friend and mix-like durable/live notifications

## Major frontend additions/changes

- navigation simplified to DJ / Discover / Community / Library
- global user search, notification dropdown, message badge, profile avatar
- Community tabs: Friends / Explore / Discussions / People
- people search, discovery, friend requests, friend management
- social-first public profiles with tabs and relationship actions
- real conversations inbox instead of manual username loading
- native Share Mix composer and playable shared-mix cards
- persistent global player across routes
- Music Identity period selector and richer factual analytics
- Music Identity visibility selector: Only me / Friends / Everyone
- reduced placeholder Listening DNA prominence
- old Forum/Social routes retained as redirects

## Database migration

`d9e4a71f3c10_add_music_social_graph.py`

Adds social graph tables and Community metadata and upgrades Music Identity visibility.

## ML boundary

No new ML/AI behavior is implemented. `music_identity_service.py` remains deterministic factual aggregation. Listening DNA remains a stable empty contract for later model integration.

## Verification performed in the implementation environment

- backend tests: 51 passed
- backend coverage: 85.99% (80% gate passed)
- Python compile check: passed
- JavaScript syntax check: passed
- direct Svelte compiler check: 32 source components passed
- full Alembic offline upgrade chain through the V3 migration: passed

The supplied archive contained Windows-native frontend dependencies. The implementation environment is Linux and offline, so it cannot reinstall the Linux-native Rolldown binding needed to run the normal Vite/SvelteKit build here. On the target Windows/Docker environment run the standard checks below after `npm ci`.

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
