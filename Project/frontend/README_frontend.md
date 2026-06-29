# Smart AI DJ Mixer — Frontend

This folder contains the frontend for the **Smart AI DJ Mixer** project.

The frontend is a **Svelte + Vite** single-page application. Its goal is to give users a simple AI-music experience: the user describes a music vibe, the interface simulates/generates an AI DJ mix, then shows the final player, selected song segments, transition explanations, and feedback buttons.

The current version uses **mock data** so the frontend can be developed before the backend, audio model, and renderer are fully ready.

---

## 1. Project idea

The app is not a normal playlist generator. It is designed to show that the AI DJ:

1. Understands the user's requested vibe.
2. Selects meaningful parts inside songs, not only full songs.
3. Plans smooth transitions between segments.
4. Renders or prepares a playable mix.
5. Explains why segments and transitions were chosen.

Main user flow:

```text
User opens homepage
→ writes a prompt or chooses a preset
→ clicks Generate Mix
→ sees progress steps
→ listens to generated mix
→ sees segment timeline
→ reads explanations
→ gives feedback
```

---

## 2. Technology stack

```text
Frontend framework: Svelte
Build tool: Vite
Language: JavaScript with JSDoc type comments
Styling: CSS inside Svelte components + global CSS variables
Deployment container: Docker + Nginx
```

### Why Svelte?

Svelte was chosen because the project needs an interactive frontend, but not a very heavy enterprise framework.

The frontend needs:

```text
Prompt input
Preset chips
Generation loading state
Audio player
Timeline interaction
Selected segment explanation
Feedback buttons
```

Svelte makes these interactions simple while keeping the code readable for a student project.

---

## 3. Folder structure

Recommended structure:

```text
frontend/
  public/
    demo_mix.mp3              # Optional local demo audio file

  src/
    App.svelte                # Main page composition
    app.css                   # Global styles and design tokens
    main.js                   # Svelte app entry point

    lib/
      components/             # Reusable UI components
        Navbar.svelte
        HeroSection.svelte
        DJPlayerCard.svelte
        PromptComposer.svelte
        MixTimeline.svelte
        SegmentDetails.svelte
        FeedbackButtons.svelte

      constants/              # Values reused across the app
        appStates.js
        presets.js

      data/                   # Temporary mock data
        mockMix.js

      services/               # Backend/mock API access layer
        mixApi.js

      stores/                 # Shared frontend state
        mixStore.js

      types.js                # JSDoc data contracts

  Dockerfile                  # Production frontend container
  nginx.conf                  # Nginx static file server config
  package.json
```

---

## 4. Main engineering decisions

### 4.1 Mock-first development

The frontend currently does not depend on the real backend. Instead, it uses `mockMix.js` and `mixApi.js`.

This allows frontend work to continue while the backend/model team works separately.

Later, only `mixApi.js` should need to change from:

```js
generateMixMock(...)
```

to a real backend request such as:

```js
fetch('/api/mixes/generate')
```

This is a healthy engineering habit because UI components do not care whether data comes from mock data or a real server.

---

### 4.2 Central store for shared state

The app state is managed in:

```text
src/lib/stores/mixStore.js
```

The store keeps:

```text
current status: idle / generating / completed / error
prompt text
duration
current progress step
progress percentage
generated mix result
selected timeline segment
error message
```

This avoids passing too many props between components and keeps the app easier to scale.

---

### 4.3 Data contracts with JSDoc

The file:

```text
src/lib/types.js
```

defines the expected shape of important objects:

```text
Mix
Segment
Transition
Preset
MixState
AppStatus
```

These are written as JSDoc comments, not TypeScript files. This keeps the project in JavaScript while still giving VS Code useful type checking.

Example purpose:

```text
A Mix must have title, duration, audio_url, segments, and transitions.
A Segment must have song, artist, role, start time, end time, score, and explanation.
A Transition must have from/to segment ids, duration, score, and explanation.
```

This helps prevent bugs when the backend is added later.

---

### 4.4 Components only display UI

Components should mostly receive data and display it.

For example:

```text
DJPlayerCard.svelte
  displays idle/generating/completed/error player state

PromptComposer.svelte
  displays prompt box, duration selector, presets, and generate button

MixTimeline.svelte
  displays selected segments and transitions

SegmentDetails.svelte
  explains the selected segment
```

The business logic should stay mainly in:

```text
mixStore.js
mixApi.js
```

This makes the code easier to change later.

---

## 5. App states

The frontend uses four main UI states:

```text
idle
  User has not generated a mix yet.

generating
  The app is building the mix and showing progress steps.

completed
  A mix is ready, so the player, timeline, explanations, and feedback appear.

error
  Something failed, so the user sees a friendly error message.
```

The states are defined in:

```text
src/lib/constants/appStates.js
```

---

## 6. Components overview

### `Navbar.svelte`

Top navigation bar.

Contains:

```text
Logo / product name
Explore link
Presets link
Sign in button
```

Currently, links are placeholders. They can be connected later when routing/authentication is added.

---

### `HeroSection.svelte`

Main hero text at the top of the page.

Purpose:

```text
Explain the app quickly.
Make the product feel like an AI music player, not a technical form.
```

---

### `DJPlayerCard.svelte`

Central visual card of the app.

It changes depending on app state:

```text
idle       → AI DJ is ready
生成ating  → progress bar and current step
completed  → mix title, score, duration, audio player
error      → friendly failure message
```

This card is important because it makes the app feel like a music product.

---

### `PromptComposer.svelte`

The main input area.

Contains:

```text
Prompt textarea
Duration selector
Generate Mix button
Preset chips
```

Preset behavior:

```text
Clicking a preset fills the prompt.
It does not generate immediately.
```

This is intentional because the user can see and edit the prompt before generating.

---

### `MixTimeline.svelte`

Shows the generated mix structure.

It displays:

```text
Segment cards
Transition cards between segments
Segment roles
Segment scores
Start/end times inside original songs
```

This is one of the most important demo components because it proves the system selected song parts, not just full songs.

---

### `SegmentDetails.svelte`

Explains the currently selected segment.

It shows:

```text
Song
Artist
Role
Original time range
Segment score
Reason for selection
```

This makes the model explainable to the user and lecturer.

---

### `FeedbackButtons.svelte`

Simple feedback UI.

Current feedback buttons:

```text
Good mix
More energy
Too much vocals
Bad transition
Too slow
Save this style
```

For now, these are visual only. Later, they should call a backend endpoint like:

```text
POST /api/feedback
```

---

## 7. Running locally in development mode

Use this while actively editing the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Then open:

```text
http://localhost:5173
```

Development mode uses Vite and supports hot reload.

That means when you edit a file, the browser updates quickly.

---

## 8. Running with Docker

The frontend also has a production-style Docker setup.

From the project root, run:

```powershell
docker compose up --build
```

Then open:

```text
http://localhost:8080
```

The Docker version works like this:

```text
Svelte source code
→ npm run build
→ dist/ static files
→ Nginx serves the files
→ browser opens localhost:8080
```

### Development vs Docker

```text
Development:
  npm run dev
  localhost:5173
  hot reload

Production Docker:
  docker compose up --build
  localhost:8080
  no hot reload
```

Use development mode while coding. Use Docker mode to verify the final course/container version.

---

## 9. Current mock generation flow

When the user clicks **Generate Mix**:

1. `PromptComposer.svelte` calls `mixStore.generate()`.
2. `mixStore.js` switches status to `generating`.
3. Progress steps are shown one by one.
4. `mixApi.js` returns `mockMix` after a delay.
5. Store status becomes `completed`.
6. Player, timeline, details, and feedback appear.

Current mock progress steps:

```text
Parsing your prompt
Finding matching segments
Building transition graph
Planning the mix
Rendering audio
Finalizing
```

These steps mirror the real backend/model pipeline planned for the project.

---

## 10. How to connect real backend later

The frontend should not be rewritten when the backend is ready.

The main file to change will be:

```text
src/lib/services/mixApi.js
```

Current mock function:

```js
export async function generateMixMock({ prompt, durationSec }) {
  // returns mockMix
}
```

Future real version could do:

```js
export async function generateMix({ prompt, durationSec }) {
  const response = await fetch('/api/mixes/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ prompt, durationSec })
  });

  if (!response.ok) {
    throw new Error('Failed to generate mix');
  }

  return await response.json();
}
```

If the backend uses background jobs, the future flow may become:

```text
POST /api/mixes/generate → returns job_id
GET /api/jobs/{job_id} → returns progress
GET /api/mixes/{mix_id} → returns final mix
```

---

## 11. Recommended next steps

Recommended build order:

```text
1. Finish static homepage and responsive layout
2. Improve player card visual design
3. Improve timeline and transition explanations
4. Make feedback buttons update local state
5. Add demo audio file to public/demo_mix.mp3
6. Add error simulation for testing the error UI
7. Connect frontend to backend API
8. Add catalog/admin pages later
```

---

## 12. Useful commands

Install dependencies:

```powershell
npm install
```

Run frontend dev server:

```powershell
npm run dev
```

Build frontend locally:

```powershell
npm run build
```

Preview production build locally:

```powershell
npm run preview
```

Run Docker production version:

```powershell
docker compose up --build
```

Stop Docker Compose:

```powershell
docker compose down
```

---

## 13. Notes for teammates

Important rules when editing this frontend:

```text
Do not put all logic in App.svelte.
Do not hardcode app states in many files.
Do not call the backend directly from visual components.
Do not change mock data shape without updating types.js.
Do not remove JSDoc comments unless replacing them with TypeScript.
```

Healthy edit locations:

```text
Change UI layout/design:
  components/*.svelte
  app.css

Change prompts/presets:
  constants/presets.js

Change mock backend result:
  data/mockMix.js

Change API/backend connection:
  services/mixApi.js

Change shared state logic:
  stores/mixStore.js

Change data contract:
  types.js
```

---

## 14. Summary

This frontend is designed to be simple now and scalable later.

Current version:

```text
No-login homepage
Prompt-first experience
Mock generation state
Generated player
Segment timeline
Transition explanations
Feedback buttons
Docker/Nginx production container
```

Future version:

```text
Real backend API
Real generated audio
Job progress polling
Save mixes after login
User history
Personalized feedback
Catalog/admin pages
```

