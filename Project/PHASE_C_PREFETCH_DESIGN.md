# Phase C Design: Prefetching the Next Track + Near-Gapless Playback

**Status:** proposed, not yet implemented.
**Scope:** sections 8-9 of the original improvement spec -- prepare the next track while the current one plays, and reduce the silence at the boundary between tracks.
**Depends on:** Phase A (multi-query retrieval, ranking) and Phase B (candidate diversity, intent split, session candidate pool cache) -- all shipped and committed.

---

## 1. What "seamless" honestly means here

Before anything else: **there is no server-rendered crossfade in the live session loop today, and this design does not add one.** I checked `audio_renderer.py` and `session_manager._resolve_and_render` directly. `_resolve_and_render` always calls `renderer.render([segment], [transition])` -- a list of exactly one segment. `PydubAudioRenderer.render` only takes the multi-segment crossfade path (`_render_composite`) when given 2+ segments; with one segment it always takes `_render_single`, a plain trim with no blending. The crossfade math in `TransitionPlanner` is computed and shown in `reasoning.transitionPlan` and the debug trace, but it's never applied to actual audio in a live session -- only `mix_service.py`'s pre-built mixes use `_render_composite`.

So "genuinely continuous playback" in this design means: **the next track's audio is already fully rendered and its URL already known before the current track ends, so the gap between `ended` and the next `play()` shrinks from "a full retrieval+render round trip" to "a fast local swap."** It does not mean an audible crossfade blend between tracks -- that would require rendering two tracks together ahead of time without knowing which "next" track will actually be needed yet, which is a materially bigger change or than what's being asked here. Building a real crossfade on top of this is a reasonable future step, not this one.

---

## 2. The key simplification that makes this tractable

Each session resolution (`create_session`, `apply_feedback`, `advance_session`) already produces one complete, independent, ready-to-play audio file and a fresh `audioUrl` -- tracks are never streamed continuously across requests. That means "prepare the next track" doesn't require touching how audio is served at all. It just means: **run the exact same resolution work early, park the result somewhere it can be handed back instantly, and let the real `advance` consume it instead of redoing the work.**

Concretely, this reuses `_resolve_and_render` completely unchanged. The only new thing is *when* it's called and *where its output goes*.

---

## 3. Backend design

### 3.1 Schema: one new column

```python
# DJSession
prepared_next_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

Stores the full result of an early `_resolve_and_render` call -- everything `create_session`/`advance_session` already compute (`track` key, `now_playing`, `reasoning`, `pipeline_trace`, plus the retrieval fingerprint from `session_candidate_pool.fingerprint_for(intent)` and a `prepared_at` timestamp) -- serialized the same way `now_playing_json`/`reasoning_json` already are. Nullable, purely additive, same migration pattern as Phase B's two columns.

### 3.2 New endpoint: prepare, don't commit

```
POST /sessions/{id}/prepare-next
```

Calls `_resolve_and_render` exactly as `advance_session` does today -- same retriever, same `session_candidate_pool` cache lookup (a warm candidate pool means this is often nearly free), same segment/render pipeline -- but writes the result into `session.prepared_next_json` instead of the live `now_playing_json`/`reasoning_json`/`intent` fields. It does not mutate anything the session currently reports as playing. If the session isn't in `"playing"` status, or a valid unconsumed prepared item already exists, this is a no-op (idempotent, safe to call speculatively).

An in-memory, per-session "already preparing" guard (same `Lock`-per-key idiom as `session_candidate_pool.py`) avoids doing the retrieval/render work twice if the frontend's prepare call and a timer both fire close together -- not a correctness requirement (a race here is just wasted duplicate work, not corruption, since only one write wins), but avoids paying for it twice.

### 3.3 The one correctness rule that matters most

**`advance_session` must re-validate the prepared item against the session's *current* intent fingerprint at the moment it's consumed, not trust that it's still valid because it existed.** Feedback can land between a prepare completing and an advance consuming it. The check:

```python
def advance_session(...):
    fingerprint = session_candidate_pool.fingerprint_for(intent)
    prepared = session.prepared_next_json
    if prepared and prepared["fingerprint"] == fingerprint and not _prepared_expired(prepared):
        # Fast path: consume it, clear the slot, persist history -- no retrieval/render.
        ...
    else:
        # Exactly today's behavior, unchanged: a real _resolve_and_render call.
        ...
```

This is the one piece of new logic `advance_session` needs. Everything else about it stays the same.

### 3.4 Feedback invalidates prepared work

`apply_feedback`, in the branch where it actually mutates the intent (`mutated is not current_intent`), clears `session.prepared_next_json` explicitly -- belt-and-suspenders alongside the fingerprint check in 3.3, and it matches the spec's own example directly: "MORE ENERGY -> discard the prepared next item." The fingerprint check alone would already prevent a stale item from being served; clearing it too means it doesn't linger uselessly in the row.

`stop_session` should also clear it, so a stopped session doesn't hold onto a prepared item nobody will ever consume.

### 3.5 Why this doesn't risk double-commit

The spec asks for protection against "two concurrent advances corrupting the session." Tracing the actual risk: `prepare-next` never writes to the fields that represent "what's currently playing" (`now_playing_json`, `intent_json`, `reasoning_json`) -- only to the separate `prepared_next_json` side-slot. `advance_session`'s fast path reads-then-clears that slot as part of one commit. The only two things that can race are (a) two `prepare-next` calls for the same session, which just means one's write overwrites the other's -- wasted work, not corruption, same "last commit wins" precedent this codebase already documents for `intent_json`/`now_playing_json`; or (b) a `prepare-next` completing after an `advance` already consumed and cleared the slot, which just means that prepare's result sits unused until the next natural refresh cycle or gets discarded by the next `apply_feedback`. Neither corrupts session state. No new locking beyond the in-memory "already preparing" guard in 3.2 is required for correctness.

---

## 4. Frontend design

This is smaller than it looks, because of the reuse in section 2: `advance()` in `sessionStore.js` doesn't need a new code path at all. It already calls `POST /sessions/{id}/advance` and applies the result -- that stays exactly as-is. The backend is just faster when a valid prepared item exists. The only new frontend work is *triggering the prepare call early*.

### 4.1 Trigger point: reuse the existing `syncTimeline` hook, not a fixed second count

`DJPlayerCard.svelte` already has `ontimeupdate={syncTimeline}` wired up and already computes `segmentBounds()` (the real playable start/end of the current segment, which the spec explicitly warns can't be assumed to be a fixed number of seconds -- confirmed necessary: one existing debug-panel session had a `whole_clip (0s-3373s)` segment, a ~56-minute "track"). Trigger the prepare call once remaining time in the segment drops below a percentage-based threshold, not an absolute one -- e.g. `remaining <= max(10, segmentDuration * 0.1)` seconds, so it behaves sensibly across both a 45-second catalog demo clip and a multi-minute Audius track, and degrades gracefully (fires "late" relative to wall-clock time, but still fires and still helps) on the pathological long-track case rather than firing needlessly early.

Fire the prepare call once per segment (a local flag reset whenever `audioUrl` changes), best-effort -- fire-and-forget, matching the spec's "prefetch fails -> normal existing advance behavior still works" requirement. No loading state, no UI change, no error surfaced to the user if it fails; `advance()`'s existing behavior is the fallback either way.

### 4.2 Reuse the existing race-protection, don't invent new state

`sessionStore.js` already has exactly the mechanism this needs: `feedbackVersion`, `lifecycleVersion`, and a shared `AbortController` slot, with the documented property that "explicit coaching feedback sent while an advance is in flight bumps feedbackVersion, so the advance's result is discarded ... coaching still interrupts and redirects mid-loop." A new `prepareNext()` call should participate in the same versioning (bump/check `feedbackVersion` the same way `advance()` does) so an in-flight prepare's result is silently discarded if feedback lands first -- consistent with the backend-side invalidation in 3.4, not a separate mechanism.

### 4.3 Optional, only if it stays simple: preloading the actual audio bytes

Section 9 asks, where possible, to preload the next rendered audio itself, not just have the backend ready to serve it fast. Once `prepare-next` returns (or once its result is folded into the next real `advance()` response, if the frontend doesn't need the URL before consuming it), the browser can be given a head start on fetching those bytes via a hidden second `<audio preload="auto">` element pointed at the known-ahead-of-time render URL. This is a nice-to-have, not a blocker for the rest of this design -- if the actual URL isn't known to the frontend before `advance()` resolves (e.g. if prepare-next's result is kept purely server-side and only exposed via the fast-path `advance()` response), skip this sub-step rather than restructuring the API to expose it early just for this.

---

## 5. File-by-file plan

| File | Change |
|---|---|
| `backend/alembic/versions/` | New migration: `prepared_next_json` on `DJSession`, nullable, additive. |
| `backend/app/database/models/session.py` | Add the column. |
| `backend/app/services/session_manager.py` | New `prepare_next(db, session)` function reusing `_resolve_and_render`; `advance_session` gains the fast-path check from 3.3; `apply_feedback` clears `prepared_next_json` when intent actually mutates (3.4); `stop_session` clears it too. |
| `backend/app/routers/sessions.py` | New `POST /sessions/{id}/prepare-next` endpoint, thin wrapper over `prepare_next`. |
| `frontend/src/lib/services/sessionApi.js` | New `prepareNext({ sessionId, signal })` -- fire-and-forget style, short-ish timeout (this one's allowed to fail silently, unlike `startSession`/`advance`/`sendFeedback`). |
| `frontend/src/lib/stores/sessionStore.js` | New `prepareNext()` sharing the existing `feedbackVersion` check pattern from `advance()`. |
| `frontend/src/lib/components/DJPlayerCard.svelte` | Call `prepareNext()` from `syncTimeline` once the percentage-based remaining-time threshold is crossed, once per segment. |

Nothing about `AudioRenderer`, `TransitionPlanner`, `SegmentSelector`, or `MultiQueryAudiusRetriever` needs to change -- this phase is entirely about *when* the existing pipeline runs and *where* its output waits, not what it computes.

---

## 6. Testing requirements

- `prepare_next` populates `prepared_next_json` without touching `now_playing_json`/`intent_json`.
- `advance_session` consumes a valid prepared item without calling the retriever again (assert the mock retriever's `retrieve()` call count).
- `advance_session` falls through to a real resolution when `prepared_next_json` is absent, expired, or its fingerprint doesn't match current intent (three separate cases).
- A feedback call that changes energy clears `prepared_next_json`, and a subsequent `advance_session` does a real resolution, not a stale-fast-path consume.
- Calling `prepare-next` twice in a row without an intervening advance doesn't duplicate retrieval work (the in-memory per-session guard from 3.2).
- `stop_session` clears any prepared item.
- Frontend: a `prepareNext()` in flight is discarded (not applied) if feedback lands before it resolves, mirroring the existing `advance()` vs. feedback test coverage already in the codebase for that race.

---

## 7. Explicit non-goals for this phase

- No real audio-level crossfade in the live session loop (section 1).
- No change to `AudioRenderer`/`TransitionPlanner`/`SegmentSelector`.
- No speculative preparation of more than one track ahead.
- No new persisted "prepared item history" -- `prepared_next_json` holds at most one entry, overwritten or cleared, never accumulated.
