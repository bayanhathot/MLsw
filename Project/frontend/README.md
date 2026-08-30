# Cuemix frontend

SvelteKit 2/Svelte 5 client for the Cuemix AI DJ, persistent mix library, community forum, and account features.

## Run locally

The default API prefix is same-origin `/api`. Vite proxies that prefix to `http://127.0.0.1:5000` and strips `/api`, so start the FastAPI backend on port 5000 before running:

```sh
npm ci
npm run dev
```

Set `PUBLIC_API_PROXY_TARGET` to change the Vite development proxy target. Set `PUBLIC_API_BASE_URL` only when a deployment intentionally serves the API on a different origin; the same-origin proxy is preferred because cookie authentication then needs no browser-specific CORS setup.

The production image serves the static build with unprivileged Nginx. Nginx proxies `/api/` (including notification WebSockets) to the Compose `backend` service.

## User routes

- `/` — prompt-driven AI DJ session and media-event-driven player.
- `/feed` — Discover: published mixes with full segment playback, likes, and saves.
- `/library` — authenticated draft generation, editing, publishing, and saved mixes.
- `/studio` — authenticated exact-moment library, manual mix timeline,
  transition controls/previews, immutable revision publishing, saved-moment
  auto-mix, a synchronized draggable waveform with analysis/AI overlays, and
  confirm-before-apply AI suggestions. Exact numeric controls remain available
  as the accessible/mobile and waveform-error fallback.
- `/community` — Friends / Explore / Discussions / People: posts, anonymous mode, attachments, comments, reversible votes, and the social graph.
- `/messages` — authenticated direct messages, attachments, durable notifications, and live notification refresh.
- `/users/[username]` — public listener profiles; `/profile` is the authenticated owner view with Music Identity analytics.
- `/login` and `/register` — HTTP-only cookie authentication.

`/forum` and `/social` still exist only as compatibility redirects to
`/community` and `/messages` respectively.

## Quality gates

```sh
npm run check
npm run lint
npm test
npm audit --audit-level=moderate
npm run build
npx playwright install chromium
npm run test:e2e
```

Vitest covers the shared API client and response adapters. `svelte-check`,
ESLint, and Prettier cover components and routes. Playwright exercises public
navigation, guest route protection, and authenticated library/profile/social
routes against the production build with controlled API fixtures.

CI additionally runs four Playwright integration files against a real
FastAPI/PostgreSQL/Redis stack: realtime delivery, Profile statistics/privacy,
persistent DJ coaching memory, and the complete CueMix product journey. The
journey uploads and analyzes original generated WAV files through the real job
queue, edits and previews their segments in Studio, renders and publishes the
mix, plays it from Library, and verifies that Profile analytics changed. These
real-backend tests are required before container images can be built or
deployed.

## API conventions

All services use `src/lib/services/api.js`. It provides cookie credentials, timeout/cancellation, structured HTTP errors, FastAPI validation-detail parsing, and deployment-safe backend media URLs. Session playback uses `/sessions` as the canonical live-session API. `/mixes` is reserved for persistent/social mix records.

The player never treats a requested play as proof of playback. Native `play`, `pause`, `waiting`, `canplay`, `ended`, and `error` events update the store, and segment players respect each segment's start/end bounds.
