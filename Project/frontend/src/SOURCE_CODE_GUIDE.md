# File: SOURCE_CODE_GUIDE.md

## Purpose
This document gives a detailed file-by-file guide to the frontend architecture.

# Zonix Frontend Source Code Guide

## Purpose
This document explains the structure of the Zonix SvelteKit frontend and how the files work together. It is meant for teammates, the lecturer, and future maintainers.

## High-level product flow
Zonix is an AI DJ interface. The user describes a vibe, starts a continuous AI DJ session, listens through the fixed bottom control deck, and guides future moments with feedback buttons.

The main flow is:

1. The home route shows the hero and full prompt composer.
2. The user enters a prompt or selects a preset chip.
3. `sessionStore.start()` simulates starting the AI DJ session.
4. The prompt hides so the screen feels like a listening experience.
5. The bottom player shows the current AI DJ moment and Coach the DJ controls.
6. The user can click Change vibe to reopen a compact prompt panel.
7. The user can stop the session, which returns the page to the full prompt state.

## Main architecture

### Routes
- `routes/+layout.svelte`: shared layout for every page. Imports global CSS and displays the navbar.
- `routes/+page.svelte`: main guest homepage and AI DJ flow. Controls prompt visibility and passes state into components.
- `routes/login/+page.svelte`: placeholder login page for future accounts.
- `routes/register/+page.svelte`: placeholder register page for future accounts.

### Components
- `Navbar.svelte`: top navigation and logo.
- `HeroSection.svelte`: brand headline and hero waveform visuals.
- `PromptComposer.svelte`: prompt input, quick presets, Start AI DJ / Update vibe behavior.
- `DJPlayerCard.svelte`: fixed bottom AI DJ control deck with play/pause, stop, progress, volume, and coach buttons.
- `FeedbackButtons.svelte`: reusable standalone feedback card, kept for future pages even though feedback is now mostly inside the player deck.

### State and data
- `stores/sessionStore.js`: central state manager. Components read from it and call its methods.
- `services/sessionApi.js`: fake async API layer. Replace this later with real backend calls.
- `data/mockSession.js`: demo session data that simulates backend/model output.
- `constants/appStates.js`: all legal session states.
- `constants/presets.js`: quick-start prompts shown in the prompt composer.
- `types.js`: JSDoc type definitions that document the frontend/backend data contract.

## Why the prompt hides
The prompt is important before starting, but after playback begins the interface should feel like a music app, not a form. The home page therefore uses local state `promptPanelOpen` plus derived states to decide whether to show:

- the full prompt composer,
- a small Current vibe strip, or
- the compact Change vibe prompt.

## Why the bottom player is different from Spotify
Zonix is not only switching between songs. The app plans continuous DJ-style segments and transitions. Therefore the bottom player contains normal music controls plus AI-specific controls:

- Coach the DJ buttons,
- current flow status,
- stop AI DJ,
- future vibe updates.

## Backend integration plan
When the backend is ready, replace the mock functions in `services/sessionApi.js` with real HTTP calls:

- `startSessionMock` -> `POST /sessions/start`
- `sendFeedbackMock` -> `POST /sessions/{session_id}/feedback`
- `stopSessionMock` -> `POST /sessions/{session_id}/stop`

The UI should not need major changes if the backend returns objects matching the types in `types.js`.

## Asset note
Binary image files such as `assets/hero.png` cannot contain source comments. Their purpose is documented here and in `assets/ASSET_NOTES.md`.
