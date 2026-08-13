# Zonix frontend source

This folder is the SvelteKit `src` tree, not a standalone package -- there is
nothing here to copy into another project. For setup, routes, and quality
gates, see [../README.md](../README.md).

`SOURCE_CODE_GUIDE.md`, `ZONIX_BRAND_APPLIED.md`, and
`ZONIX_FINAL_DESIGN_NOTES.md` in this folder are archived design/architecture
snapshots from an earlier, mock-only iteration (before auth, persistent
mixes, community, messaging, uploads, and Music Identity existed). Each is
marked archived at the top; none of them describe current behavior.

To orient in the current code, start with:

1. `routes/+page.svelte` — the AI DJ prompt/session flow.
2. `lib/stores/sessionStore.js` and `lib/stores/authStore.js` — client state.
3. `lib/services/` — the API adapters (one file per backend resource).
4. `lib/components/DJPlayerCard.svelte` — the bottom AI DJ control deck.
