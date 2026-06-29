# Smart AI DJ Mixer — Frontend

This folder contains the **Svelte + Vite frontend** for the Smart AI DJ Mixer project.

The current frontend direction is a **prompt-first continuous AI DJ experience**:

> The user describes a vibe, clicks **Start AI DJ**, and the app keeps playing matching song moments until the user stops.

The frontend is intentionally designed to feel like a modern music player, not a technical ML dashboard. Internal model details such as segment scores, transition scores, and raw timestamps are hidden from the normal user interface. A simplified optional **AI reasoning** panel remains available for demo/lecturer explanation.

---

## 1. Product Goal

The frontend should prove the main product idea:

1. A user can describe a music vibe naturally.
2. The AI DJ starts a continuous listening session.
3. The user sees what is currently playing: song, artist, album/source, cover, and vibe.
4. The user can guide the session using simple feedback.
5. Technical reasoning is available only when needed, not shown by default.

The product should feel closer to:

```text
Spotify / YouTube Music + AI DJ
```

not:

```text
ML dashboard with raw model scores
```

---

## 2. Current MVP User Flow

```text
User opens home page
→ User writes prompt or clicks preset
→ Preset fills the prompt
→ User clicks Start AI DJ
→ App shows startup progress
→ Player appears with current song details
→ User can pause/play or stop session
→ User can send simple feedback
→ User can optionally open AI reasoning
```

There is **no duration selector** anymore because the product is now a continuous AI DJ session, not a fixed 3-minute generated file.

---

## 3. Technology Stack

```text
Frontend framework: Svelte
Build tool: Vite
Language: JavaScript with JSDoc typing
Styling: Plain CSS with global design tokens
Container serving: Nginx production container
```

### Why Svelte?

Svelte is lightweight and good for building an interactive MVP quickly. It allows each component to contain:

```text
logic
+ HTML structure
+ local CSS
```

This is useful for the project because the UI has changing states: idle, starting, playing, stopped, and error.

### Why JSDoc?

The project uses JavaScript, but JSDoc comments give VS Code useful type checking.

This keeps the code easier than TypeScript for now, while still documenting the expected frontend/backend data shapes.

---

## 4. Folder Structure

```text
src/
  App.svelte
  app.css
  main.js

  assets/
    hero.png

  lib/
    components/
      Navbar.svelte
      HeroSection.svelte
      PromptComposer.svelte
      DJPlayerCard.svelte
      FeedbackButtons.svelte
      AIReasoningPanel.svelte

    constants/
      appStates.js
      presets.js

    data/
      mockSession.js

    services/
      sessionApi.js

    stores/
      sessionStore.js

    types.js
```

---

## 5. Important Files

### `src/main.js`

Entry point of the Svelte app.

It imports global CSS, loads `App.svelte`, and mounts it into the HTML element with id `app`.

Browser flow:

```text
index.html
→ main.js
→ App.svelte
→ frontend UI
```

---

### `src/App.svelte`

Main page composition file.

This file does not contain all business logic. It connects the major page sections together:

```text
Navbar
HeroSection
DJPlayerCard
PromptComposer
FeedbackButtons
AIReasoningPanel
```

It reads state from `sessionStore.js` and decides which components should appear.

Engineering rule:

```text
App.svelte should arrange the page.
State logic belongs in stores.
Backend/mock calls belong in services.
Visual details belong in components.
```

---

### `src/app.css`

Global styling and design tokens.

It defines shared CSS variables such as:

```css
--bg-main
--bg-card
--text-main
--text-muted
--accent
--accent-2
--radius-lg
--shadow-soft
```

This makes the design easier to change later. For example, changing the accent color should happen mostly in `app.css`, not in every component.

---

## 6. Components

### `Navbar.svelte`

Top navigation bar.

Current purpose:

```text
Show product identity
Show simple navigation placeholders
Show Sign in button placeholder
```

Login is not implemented yet. The app should work for guests first.

---

### `HeroSection.svelte`

Main marketing message.

Explains the product in a simple way:

```text
Tell the AI DJ your vibe.
It keeps mixing the best song moments until you stop.
```

This section helps the user understand the app before interacting.

---

### `PromptComposer.svelte`

Prompt input section.

Contains:

```text
Prompt textarea
Preset chips
Start AI DJ button
```

Important decision:

```text
Preset chips fill the prompt, but do not start the session immediately.
```

This lets the user see and edit the generated prompt before clicking **Start AI DJ**.

The old duration selector was removed because the app now plays continuously until stopped.

---

### `DJPlayerCard.svelte`

Main user-facing music player.

Shows:

```text
Current vibe
Cover image
Song title
Artist
Album/source
Play / pause button
Stop AI DJ button
Startup progress
Stopped state
Error state
```

It intentionally does **not** show:

```text
mix score
segment score
transition score
start_sec
end_sec
graph edge details
```

Those details are useful for the model and debugging, but not for the normal listener.

---

### `FeedbackButtons.svelte`

Simple user feedback controls.

Current feedback examples:

```text
Good vibe
More energy
Less vocals
Smoother
Surprise me
Stop this style
```

For the MVP, feedback is stored visually/mock-only. Later it should be sent to the backend and used as a learning signal.

---

### `AIReasoningPanel.svelte`

Optional explanation panel.

Hidden by default.

Purpose:

```text
Let the lecturer/demo user inspect why the AI DJ chose the current song moment.
```

It uses human-readable explanations, not raw ML scores.

Example explanation style:

```text
The AI DJ selected this moment because it matches the emotional vocal vibe and gives a smooth entry.
```

---

## 7. Constants

### `src/lib/constants/appStates.js`

Defines legal UI states:

```text
idle
starting
playing
buffering_next
stopped
error
```

Why this exists:

```text
State names should be centralized.
Components should not invent random state strings.
```

The old state `completed` was removed because the app is not generating a finished fixed-length mix anymore. It is running an AI DJ session.

---

### `src/lib/constants/presets.js`

Defines quick prompt presets.

Examples:

```text
Gym Energy
Tarab
Chill
Party
Focus
Classic Arabic
Late Night
```

Each preset has:

```text
label: short visible chip text
prompt: full prompt inserted into the composer
```

---

## 8. Mock Data and Services

### `src/lib/data/mockSession.js`

Contains fake session data used before the real backend exists.

It includes:

```text
session id
vibe label
current song title
artist
album/source
cover image
audio url placeholder
AI reasoning text
```

This lets the frontend be built and tested without waiting for the model/backend.

---

### `src/lib/services/sessionApi.js`

Mock API layer.

Current functions:

```text
startSessionMock()
sendFeedbackMock()
stopSessionMock()
```

These functions simulate backend behavior with small delays.

Later this file should be changed to real API calls such as:

```text
POST /sessions/start
POST /sessions/{session_id}/feedback
POST /sessions/{session_id}/stop
POST /sessions/{session_id}/next
```

Engineering rule:

```text
Components should not call fetch directly.
Backend communication should be isolated in services.
```

This makes backend changes safer.

---

## 9. Store

### `src/lib/stores/sessionStore.js`

Central state manager for the frontend.

It stores:

```text
status
prompt
progress
currentStep
session
isPlaying
feedbackMessage
reasoningOpen
error
```

It exposes actions:

```text
setPrompt()
start()
togglePlay()
stop()
sendFeedback()
toggleReasoning()
reset()
```

Engineering reason:

```text
The store is the single source of truth.
```

Without a store, many components would each manage their own state, which becomes hard to debug.

Important safety rule in the store:

```text
togglePlay() only works while the session is playing.
```

This prevents impossible states like:

```text
status = stopped
isPlaying = true
```

---

## 10. Types

### `src/lib/types.js`

Shared frontend data contracts written with JSDoc.

Defines:

```text
AppStatus
Preset
NowPlaying
AIReasoning
Session
SessionState
```

Why this matters:

```text
The frontend and backend need to agree on object shapes.
VS Code can catch wrong property names.
Future backend integration becomes easier.
```

Example:

```text
A Session has id, vibeLabel, nowPlaying, audioUrl, and reasoning.
```

---

## 11. Development Commands

From the `frontend` folder:

```powershell
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

Use this mode while designing because Vite gives hot reload.

---

## 12. Docker / Production Check

From the project root, run:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8080
```

Use Docker to verify the course-style production container.

Important difference:

```text
npm run dev
→ Vite development server
→ localhost:5173
→ hot reload

docker compose up --build
→ production build served by Nginx
→ localhost:8080
→ no hot reload
```

---

## 13. Current MVP Decisions

### Keep

```text
No-login home page
Prompt composer
Preset chips
Start AI DJ button
Current song player
Cover image
Artist / album details
Play / pause
Stop AI DJ
Simple feedback
Optional AI reasoning
```

### Removed from main user UI

```text
Duration selector
Mix score
Segment score
Transition score
Segment timeline by default
Raw start/end timestamps
Technical graph details
```

### Postpone

```text
Login
Save mix
History
Share
Catalog page
Admin page
Collaborative party mode
Real infinite queue
Real backend audio chunking
```

---

## 14. Future Backend Integration Plan

The frontend is designed around session APIs.

Future endpoints may be:

```http
POST /sessions/start
POST /sessions/{session_id}/next
POST /sessions/{session_id}/feedback
POST /sessions/{session_id}/stop
```

Expected future behavior:

```text
Start session
→ backend returns first audio chunk and now-playing metadata
→ frontend plays it
→ before it ends, frontend requests next chunk
→ backend returns next continuation
→ session continues until user stops
```

For now, this is mocked.

---

## 15. Team Development Rules

To keep the frontend clean:

1. Do not put all code inside `App.svelte`.
2. Add visual UI in `components/`.
3. Add fixed values in `constants/`.
4. Add mock data in `data/`.
5. Add backend calls only in `services/`.
6. Add shared state only in `stores/`.
7. Update `types.js` when backend JSON shapes change.
8. Keep ML/debug details out of the main user UI.
9. Use optional reasoning panels for explainability.
10. Run Docker before submission to verify the production container.

---

## 16. Quick Test Checklist

After running the app:

```text
1. Open the page.
2. Click a preset.
3. Confirm the prompt fills.
4. Click Start AI DJ.
5. Confirm startup progress appears.
6. Confirm player appears with song details.
7. Click pause/play.
8. Click feedback.
9. Open AI reasoning.
10. Click Stop AI DJ.
11. Confirm feedback disappears and stopped state appears.
```

If all steps pass, the frontend MVP is working.

---

## 17. Current Product Sentence

```text
Tell the AI DJ your vibe, and it keeps mixing the best song moments until you stop.
```
