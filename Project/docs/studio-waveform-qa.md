# Studio waveform architecture and QA

## Authority contract

- `routes/studio/+page.svelte` owns the canonical `startMs`, `endMs`, and
  `currentTimeMs` values (stored in exact milliseconds).
- `WaveformSegmentEditor.svelte` is a visual/interaction adapter. WaveSurfer is
  bound to Studio's existing `HTMLAudioElement`; it is not a second player.
- Numeric inputs, set-current buttons, waveform handles, seeking, looping,
  saving, and AI apply all update or consume the same range.
- The backend publishes the configured minimum and maximum segment durations
  and revalidates ownership, track bounds, duration, decodability, and silence
  when a segment is saved.
- Persisted highlight and phrase analysis is displayed as metadata overlays.
  The browser does not recompute DSP analysis or persist waveform peaks.
- An AI range is an orange overlay until the user chooses Apply. Play AI and
  Compare do not mutate the user's range; Keep Mine removes the suggestion.

## Automated evidence

| Layer | Coverage |
| --- | --- |
| Unit | Millisecond/position conversion and range min/max/bounds normalization |
| Backend | Studio search exposes phrase markers and authoritative duration limits |
| Browser | Numeric-to-waveform synchronization, handle drag, waveform seek, decode failure fallback, and confirm-before-apply AI bounds |
| Regression | Full frontend check, lint, unit, production build, and runnable Chromium E2E suite |

## Deployment acceptance checklist

Run this after the next green VM deployment and record the deployed SHA.

- Desktop Chromium: choose catalog and Audius tracks; waveform, playhead,
  highlight, and phrase markers load without console/CORS errors.
- Drag both handles and the whole selection; exact numeric fields follow and
  never violate the server-provided duration limits.
- Change numeric bounds to millisecond precision; the region follows and Save
  persists the identical values after reload.
- Click the waveform to seek, then use Set current as start/end and looped Play
  segment; there is no second or overlapping player.
- Request an assistant bound suggestion; verify it is visually distinct, Play
  AI and Compare do not mutate the range, Apply does, and Keep Mine restores the
  user's preview range.
- Exercise a long Audius track and a mobile viewport; confirm the waveform stays
  responsive and numeric controls remain practical.
- Force an audio fetch/decode failure; confirm the error is readable and the
  numeric editor remains usable.
- Re-run save, queue, transition preview, full render, publish, and immutable
  duplicate flows to prove the waveform adapter did not alter those contracts.

Production verification is intentionally still open until these checks run on
the public VM; local mocked audio cannot establish provider CORS or VM resource
behavior.
