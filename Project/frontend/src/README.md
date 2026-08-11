# File: README.md

## Purpose

This document explains how to use the documented Zonix frontend source.

# Zonix Frontend Source

This folder contains the documented SvelteKit `src` source for the Zonix AI DJ frontend.

## What Zonix does

Zonix is a guest-first AI DJ interface. A user describes a vibe, starts the AI DJ, and then coaches the session with simple feedback controls.

## Important UX behavior

- The prompt is visible before starting.
- The prompt hides after starting so the UI becomes a listening experience.
- A compact Change vibe panel can reopen the prompt during playback.
- Stopping the AI DJ shows the full prompt again.
- The bottom player is an AI DJ control deck, not only a normal song player.

## How to install in your SvelteKit project

Copy these files into your project `frontend/src/` folder.

Then run:

```powershell
cd frontend
npm run dev
```

For Docker:

```powershell
cd ..
docker compose build --no-cache frontend
docker compose up
```

## Main files to read first

1. `SOURCE_CODE_GUIDE.md`
2. `routes/+page.svelte`
3. `lib/stores/sessionStore.js`
4. `lib/components/DJPlayerCard.svelte`
5. `lib/components/PromptComposer.svelte`
