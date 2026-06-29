# File: ZONIX_FINAL_DESIGN_NOTES.md

## Purpose
This document explains the final MVP design choices and why the interface looks/behaves this way.
It is not executed by the app; it is design documentation for the project.

# Zonix Final MVP Frontend Design

This source package applies the final selected design direction:

- Clean dark streaming-app feel, without copying Spotify structure.
- Calmer blue accent instead of overly bright cyan.
- Hero + prompt as the main guest experience.
- No heavy library/sidebar/recent-history panels for the MVP.
- Fixed bottom AI DJ control deck.
- Bottom deck is not a normal track switcher: it focuses on continuous AI mixing and coaching the vibe.

## Key UX decisions

1. The prompt remains the main action.
2. Shortcut chips are text-only so they can later become recent prompts or saved vibes.
3. The bottom player includes:
   - current moment metadata,
   - play/pause,
   - stop AI DJ,
   - current flow progress,
   - coach-the-DJ buttons.
4. Raw model scores and technical graph details are hidden from normal users.

## Files mainly changed

- `src/app.css`
- `src/routes/+layout.svelte`
- `src/routes/+page.svelte`
- `src/lib/components/Navbar.svelte`
- `src/lib/components/HeroSection.svelte`
- `src/lib/components/PromptComposer.svelte`
- `src/lib/components/DJPlayerCard.svelte`
- `src/lib/constants/presets.js`
- `src/lib/data/mockSession.js`
