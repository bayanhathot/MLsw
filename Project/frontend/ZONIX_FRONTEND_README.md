# Zonix Frontend README

> **Archived implementation snapshot.** This document describes the early
> mock-only MVP and is retained only for project history. It is not a setup or
> architecture reference. Use [README.md](README.md) and the repository root
> [README.md](../README.md) for the current authenticated, persistent frontend.

This README explains the purpose, structure, and current behavior of the Zonix frontend.

---

## 1. Frontend purpose

The frontend is the user-facing part of Zonix.

It lets the user:

- Open the Zonix app.
- Read the product message.
- Enter a vibe prompt.
- Choose a preset vibe.
- Start an AI DJ session.
- See the current session/player state.
- Coach the DJ using feedback buttons.
- Stop the AI DJ session.
- Visit login/register placeholder pages.

The frontend does not contain the real AI logic. Its job is to collect user input, send it to the backend, and display the result returned by the backend.

---

## 2. Frontend technology

The frontend uses:

```text
SvelteKit
JavaScript with JSDoc
CSS
Vite
Nginx for Docker production serving
```

In development, SvelteKit runs on:

```text
http://localhost:5173
```

In Docker, Nginx serves the built frontend on:

```text
http://localhost:8080
```

---

## 3. Important frontend behavior

The current MVP behavior is:

```text
1. User enters a vibe prompt.
2. User clicks Start AI DJ.
3. Frontend sends the prompt to FastAPI.
4. Backend returns a session.
5. Frontend shows the returned now-playing data.
6. User can click feedback buttons.
7. Frontend sends feedback to backend.
8. User can stop the session.
```

Important UI/product decisions:

- The app is a continuous AI DJ session, not a fixed-duration generated mix.
- The bottom player is an AI DJ control deck, not only a normal song player.
- Feedback buttons are part of the main product idea.
- Preset chips help the user quickly fill the prompt.
- Login/register pages exist as placeholders for future authentication.

---

## 4. Frontend folder structure

```text
frontend/
  src/
    app.css
    app.html
    routes/
      +layout.svelte
      +layout.js
      +page.svelte
      login/+page.svelte
      register/+page.svelte
    lib/
      components/
      constants/
      data/
      services/
      stores/
      types.js
    assets/
  static/
    brand/
  Dockerfile
  nginx.conf
  svelte.config.js
  vite.config.js
```

---

## 5. Important files

### `src/routes/+page.svelte`

Purpose:

Main home page of the app.

What it does:

- Displays the main Zonix landing/app screen.
- Uses the hero section, prompt composer, and AI DJ player components.
- Reads state from `sessionStore.js`.
- Calls store methods when the user starts, stops, or sends feedback.

---

### `src/routes/+layout.svelte`

Purpose:

Global layout wrapper for all frontend routes.

What it does:

- Imports global styles.
- Renders child pages.
- Keeps the app structure shared across pages.

---

### `src/routes/+layout.js`

Purpose:

Controls SvelteKit rendering mode.

What it does:

- Disables server-side rendering for this static frontend.
- Enables prerendering/static build behavior.
- Makes the app suitable for Nginx static serving in Docker.

---

### `src/app.html`

Purpose:

Global SvelteKit HTML template.

What it does:

- Defines the base HTML document.
- Lets SvelteKit inject page head content.
- Lets SvelteKit inject the actual app body.

Important:

The placeholders must appear only in the real head/body locations:

```html
%sveltekit.head% %sveltekit.body%
```

They must not be written inside comments, because that can break the build and show `%sveltekit.head% %sveltekit.body%` in the browser.

---

### `src/app.css`

Purpose:

Global styling for the Zonix frontend.

What it does:

- Defines the dark visual theme.
- Defines page layout styles.
- Defines button/card/player styling.
- Provides the polished UI look.

---

## 6. Components

Components are located in:

```text
src/lib/components/
```

### `Navbar.svelte`

Purpose:

Top navigation bar.

What it does:

- Shows the Zonix logo/brand.
- Provides navigation links.
- Links to login/register pages.

---

### `HeroSection.svelte`

Purpose:

Main landing message.

What it does:

- Explains the value of Zonix.
- Presents the product as an AI DJ that helps the user stay in the zone.

---

### `PromptComposer.svelte`

Purpose:

Prompt input area.

What it does:

- Lets the user write the desired vibe.
- Shows quick preset chips.
- Sends prompt changes back to the store.
- Lets the user start the AI DJ session.

---

### `DJPlayerCard.svelte`

Purpose:

Main AI DJ player/control card.

What it does:

- Displays current now-playing data from the backend session.
- Shows session/player state.
- Contains play/pause style UI behavior.
- Contains Stop AI DJ action.
- Contains or works with feedback buttons.

---

### `FeedbackButtons.svelte`

Purpose:

Coach-the-DJ controls.

What it does:

- Shows feedback buttons such as Good vibe, More energy, Less vocals, and Smoother.
- Sends selected feedback to the store.
- The store sends that feedback to the backend.

---

## 7. State management

Main file:

```text
src/lib/stores/sessionStore.js
```

Purpose:

This file is the central frontend state manager.

It stores:

- Current prompt.
- Current app status.
- Current progress/startup message.
- Current session returned from backend.
- Play/pause state.
- Selected feedback.
- Error state.

It exposes methods such as:

```text
setPrompt(prompt)
start()
togglePlay()
stop()
sendFeedback(feedback)
toggleReasoning()
reset()
```

Why it exists:

Instead of spreading state logic across many UI components, the store keeps product behavior in one place.

---

## 8. Backend API connection

Main file:

```text
src/lib/services/sessionApi.js
```

Purpose:

This file connects the frontend to the FastAPI backend.

Current backend base URL:

```js
const API_BASE_URL = 'http://localhost:5000';
```

Functions:

```text
startSession({ prompt })
sendFeedback({ sessionId, feedback })
stopSession({ sessionId })
```

Requests sent:

```text
POST /sessions/start
POST /sessions/{session_id}/feedback
POST /sessions/{session_id}/stop
```

Important:

The UI components do not call `fetch()` directly. They call store methods. The store calls `sessionApi.js`. This keeps the frontend cleaner.

---

## 9. Constants and data

### `src/lib/constants/appStates.js`

Purpose:

Defines the legal app states.

Current states:

```text
idle
starting
playing
buffering_next
stopped
error
```

---

### `src/lib/constants/presets.js`

Purpose:

Defines quick vibe preset chips.

Examples:

```text
deep work focus
late night coding
emotional Arabic vocals
gym energy
chill and relax
party warmup
```

---

### `src/lib/data/mockSession.js`

Purpose:

Contains old/demo mock session data.

Current role:

This may remain as a fallback/reference, but the connected frontend now uses FastAPI through `sessionApi.js`.

---

### `src/lib/types.js`

Purpose:

Documents the frontend data shapes using JSDoc.

Why it helps:

It gives better structure and editor support without converting the project fully to TypeScript.

---

## 10. Running the frontend locally

From the frontend folder:

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

The backend should also be running on:

```text
http://localhost:5000
```

---

## 11. Building the frontend

From the frontend folder:

```powershell
npm run build
```

This creates a production build in:

```text
frontend/build/
```

The Docker container serves this built folder through Nginx.

---

## 12. Running the frontend with Docker

From the project root:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8080
```

---

## 13. Docker frontend files

### `frontend/Dockerfile`

Purpose:

Builds and serves the SvelteKit frontend.

What it does:

1. Uses Node to install dependencies and run `npm run build`.
2. Uses Nginx to serve the generated static build.
3. Exposes port 80 inside the container.

---

### `frontend/nginx.conf`

Purpose:

Configures Nginx for the SvelteKit static app.

What it does:

- Serves files from `/usr/share/nginx/html`.
- Falls back to `index.html` for frontend routes like `/login` and `/register`.

---

## 14. Current limitations

Current frontend limitations:

- Login/register pages are placeholders.
- No real audio playback is connected yet.
- Volume/play/pause behavior is mostly UI-level.
- No saved sessions or user history yet.
- No real user account state yet.
- No real library/catalog UI yet.

---

## 15. Next frontend steps

Recommended next frontend tasks:

1. Show a clearer loading state while waiting for backend.
2. Display backend error messages more specifically.
3. Add a visible current prompt/vibe strip while playing.
4. Add a Next Segment button after the backend supports it.
5. Connect real audio URLs when the backend provides them.
6. Improve login/register once authentication is implemented.
7. Add tests for frontend components later.

---

## 16. Frontend summary

The frontend currently works as the visual/control layer of Zonix.

It is responsible for:

```text
User input
UI state
Calling backend APIs
Displaying session results
Sending feedback
```

It is now connected to the backend and ready for the next backend improvement: catalog-based segment selection.
