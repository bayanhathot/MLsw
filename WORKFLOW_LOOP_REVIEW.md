# Cuemix AI-DJ Session Workflow — Read-Only Loop Review

**Status:** review only, no behavior changed. Written for a teammate who understands Python/JS but hasn't read this codebase yet. Every claim below is anchored to a specific file and function so it can be checked against the source directly.

**Scope:** the live, continuous AI-DJ "session" loop only — `create_session` → play → `advance_session`/`prepare_next` → `stop_session`, as wired through `app/routers/sessions.py`, `app/services/session_manager.py`, the five pipeline stages under `app/services/pipeline/`, and the frontend's `sessionStore.js`/`DJPlayerCard.svelte`. The separate "Mixes" feature (`mix_service.py`, multi-segment pre-built mixes) is out of scope except where it's directly relevant to something the session loop deliberately does *not* do (see §8).

---

## 1. The full lifecycle, start to finish

**Starting a session.** The user types a prompt into `PromptComposer` and the page calls `sessionStore.start()` (`frontend/src/lib/stores/sessionStore.js`). That sets `status = STARTING`, opens an `AbortController`, and calls `startSession()` (`frontend/src/lib/services/sessionApi.js`), which POSTs `/sessions/start` with a 45-second timeout (the pipeline can genuinely take that long — see §2). On the backend, `routers/sessions.py:start_session` hands the prompt straight to `session_manager.create_session` (`app/services/session_manager.py`).

`create_session` first calls `_initial_intent`, which runs the configured `VibeUnderstander.understand(prompt)` to get a structured `PromptIntent`, then — only if that intent came out completely neutral (medium energy, neutral vocals, no artist) and the caller is a logged-in user — walks the user's learned `UserPreference` rows and biases the intent toward whichever past feedback scored highest (`_apply_preference`). It generates a session id up front (`session_id = f"session_{uuid4().hex}"`) specifically so the very first resolution can key the candidate-pool cache correctly (see §3), then calls the shared workhorse `_resolve_and_render(...)` — the same function every subsequent step in this document (`apply_feedback`, `advance_session`, `prepare_next`) calls too. That function runs candidate retrieval → segment selection → transition planning → audio rendering (§2) and returns everything needed to build the response. `create_session` stamps the `pipeline_trace` with a `vibe_understander` entry (`invoked: True`, since the LLM/deterministic parser really did run), constructs a new `DJSession` row with `status="playing"`, and commits it. The FastAPI response is a `SessionRead` Pydantic model; the frontend's `normalizeSession` (`sessionApi.js`) converts it (tolerating both camelCase and legacy snake_case field names) into the `Session` shape the store and UI use, and `sessionStore.start()` flips `status = PLAYING`, `playbackRequested = true`, `isPlaybackBuffering = true`.

**Playing.** `DJPlayerCard.svelte` derives `audioUrl` from the session and, in a `$effect`, calls `audioElement.play()` whenever `canControl && playbackRequested` is true. `ontimeupdate` drives `syncTimeline()`, which tracks listening time for analytics, recomputes the playable window (`segmentBounds()`), and — this is the Phase-C addition — calls `maybePrepareNext(bounds)` once the track is within a percentage-based distance of ending (§7).

**Looping without user input.** When the audio genuinely ends (`handleAudioEnded`) and there's no further *local* segment queued (`hasNext` is false — true for essentially every live session, since a session resolution always renders exactly one segment; see §8), the component calls `onMediaEnded()` → `sessionStore.mediaEnded()`, which flips a few UI flags and fires `advance()` without awaiting it. `advance()` POSTs `/sessions/{id}/advance` → `routers/sessions.py:advance_session` → `session_manager.advance_session`. This function first checks whether `prepare_next` (fired earlier, while the track was still playing) already parked a still-valid result; if so it applies that directly with no network/CPU work at all (the "fast path", §5). If not, it does exactly what `create_session` did — a fresh `_resolve_and_render` call — except it also passes `exclude_track_keys` (the session's recently-played tracks, so it doesn't immediately repeat) and `recent_artists` (for diversity-aware ranking, see the `WEIGHT_DIVERSITY` signal in §2). Either way, the result is appended to `played_track_keys_json`/`played_artists_json` (capped at `_PLAYED_TRACK_HISTORY = 10`), committed, and returned.

**Coaching feedback.** Clicking "More energy"/"Less vocals"/"Smoother"/"Good vibe" calls `onFeedback` → `sessionStore.sendFeedback(feedback)` → POST `/sessions/{id}/feedback` → `session_manager.apply_feedback`. This normalizes the raw string (`_normalize_feedback`) into one of `more_energy`/`less_vocals`/`smoother`/`reinforce`/`custom`, applies a fixed keyword rule to the *current* intent (`_mutate_intent` — e.g. "more energy" jumps `energy` straight to `"high"`, not a gradual nudge), and — only if the intent actually changed or the user asked for a smoother transition — re-resolves via `_resolve_and_render` against the *mutated* intent, persists the new `intent_json`, and (if the intent object itself changed) explicitly clears any parked `prepared_next_json` (§5). It also records a learned `UserPreference` row so a *future* neutral session can be biased toward this choice (closing the loop back to `_initial_intent` above). If the mutated intent matches nothing (`NoMatchingCandidate`), the session is left exactly where it was — one bad feedback mutation never errors out a live session.

**Stopping.** `sessionStore.stop()` POSTs `/sessions/{id}/stop` → `session_manager.stop_session`, which sets `status = "stopped"`, clears any parked `prepared_next_json`, and commits. The frontend flips `status = STOPPED`; `DJPlayerCard`'s `canControl` (which requires `status === PLAYING`) goes false and playback stops.

---

## 2. Every pipeline stage, in call order

All of this happens inside `session_manager._resolve_and_render` (called identically by `create_session`, `apply_feedback`, `advance_session`'s slow path, and `prepare_next`) unless noted.

1. **Prompt → Intent.** `VibeUnderstander.understand(prompt)` (`app/services/pipeline/vibe.py`), bound at startup to either `OllamaVibeUnderstander` or `DeterministicOnlyVibeUnderstander` via `VIBE_LLM_PROVIDER` (`app/services/pipeline/dependencies.py:_build_vibe_understander`). Both ultimately call into `app/services/prompt_parser.py`: `OllamaVibeUnderstander.understand` calls `parse_prompt`, `DeterministicOnlyVibeUnderstander.understand` calls `deterministic_parse` directly. Produces a `PromptIntent` (`app/schemas.py`): `mood`, `energy`, `vocals`, `genres`, `artist`, `artist_mode`, `search_query`. Full guardrail detail in §4.

2. **Intent → Queries.** `query_planner.build_queries(intent, max_queries=5)` (`app/services/pipeline/query_planner.py`) — a pure function, no I/O. Builds an ordered list of Audius search strings, most-specific-first: the artist name (if any), then — if the artist is `required` — the raw search_query promoted early (so a required-artist round isn't diluted by an unrelated genre query), then each genre, a 2-genre combo, a mood+genre combo, an energy-only fallback term if there's no genre at all, and finally the raw `search_query` (unless already promoted). Capped at 5 total.

3. **Queries → raw candidates.** `MultiQueryAudiusRetriever.retrieve` (`app/services/pipeline/audius_retriever.py`) is `session_manager`'s primary retriever (`dependencies.py:get_session_candidate_retriever`). It groups the queries into rounds of 2 (`_relaxation_rounds`, capped at `MAX_RETRIEVAL_ROUNDS = 3`) and, **sequentially round by round**, calls `audius_service.search_tracks(query, limit=CANDIDATES_PER_QUERY)` (`app/services/audius_service.py`) for each query in the round, converting each raw dict to a `Track` via `_to_track`. After each round it checks `len(pool) >= MIN_POOL_SIZE` (25) and stops early if satisfied — this is why the rounds themselves must stay sequential (a documented, previously-discussed design constraint). `search_tracks` itself is a cache-fronted wrapper (§3a) around `_search_tracks_uncached`, which makes the real HTTP call to the Audius Discovery API.

4. **Raw candidates → fused pool.** `_reciprocal_rank_fusion(rank_lists, k=RRF_K)` (same file) combines the per-query ranked key-lists into one fused order: a track appearing near the top of *multiple* query results outranks one that only appeared once, without needing Audius's own (non-comparable-across-calls) relevance score.

5. **Fused pool → ranked pool.** `_rank_by_metadata(pool, fused_order, intent, recent_artists)` calls `_score_candidates`, which scores every candidate against the intent on independent 0–1 sub-signals — retrieval position, genre match, mood match, tag overlap, a hardcoded genre→energy heuristic (only used when no real tag/mood data exists), required-artist trigram similarity, and session-diversity (`recent_artists`, `WEIGHT_DIVERSITY`) — then averages only the signals that actually had data for that candidate (missing metadata never counts *against* a track) into a `total`. Candidates are sorted by `total` descending. This breakdown is also what powers the internal debug panel.

6. **Candidates → the retriever call's return value.** Back in `session_manager._resolve_and_render`, this whole retrieval (steps 3–5) is wrapped by `orchestrator.retrieve_candidates_with_fallback` (`app/services/pipeline/orchestrator.py`): it tries the primary retriever (Audius) first, and only if that comes back *completely empty* falls through to `CatalogTrackRetriever` (`app/services/pipeline/catalog_retriever.py`) — the small seeded/uploaded local library, matched either by fuzzy artist-name similarity (`_trigram_similarity`, a pure-Python pg_trgm analogue) or a mood-bucket keyword lookup. An empty result from *both* raises `NoMatchingCandidate`, which the caller (`apply_feedback`/`advance_session`) either surfaces as a 422 or treats as "leave the session where it is."

7. **Ranked pool → one selected track.** `_resolve_and_render` picks the first candidate not already in `exclude_track_keys` (falling back to the very top match if every candidate has already been played — "loop indefinitely" is intentional once a session's pool is exhausted).

8. **Track → segment.** `SegmentSelector.select(db, track)`, bound to `LibrosaSegmentSelector` (`app/services/pipeline/segment_selector.py`). For a local catalog track with a completed librosa analysis job, this reads the cached chorus/hook window from the `catalog_tracks` row. For anything else — every Audius track, since they have no `catalog_track_id` — it's just the whole clip (`method="whole_clip"`, `start=0`, `end=track.duration_seconds` or a 40-second fallback).

9. **Segment → transition plan.** `TransitionPlanner.plan(previous_segment, segment, prefers_smoother=...)`, bound to `DeterministicTransitionPlanner` (`app/services/pipeline/transition_planner.py`). Pure arithmetic over BPM/musical-key distance: compatible tempo+key gets a long crossfade, clashing tempo or key gets a shorter hard cut, `prefers_smoother` (set by the "Smoother" feedback command) adds a fixed bonus. `previous=None` (the very first track) always gets `crossfade_ms=0, style="cut"`.

10. **Segment + transition → rendered audio.** `AudioRenderer.render([segment], [transition])`, bound to `PydubAudioRenderer` (`app/services/pipeline/audio_renderer.py`). Because the session loop always passes exactly **one** segment, this always takes the `_render_single` path: download the track's audio (`_download`, an `httpx` streaming GET capped at 15MB / 8s timeout) or read a local file, trim it to the selected window with pydub, export it as a fresh `.wav`, and return a `RenderedAudio` with the new `audio_url`. If the download/decode fails, it degrades to `is_pass_through=True` and returns the *original* remote URL untouched rather than fabricating a render.

11. **Everything → the response.** `_resolve_and_render` assembles `now_playing` (title/artist/album/cover/role/audio_url/segment), `reasoning` (a human-readable sentence about the selected moment + the transition's `notes`), and a `pipeline_trace` dict (one sub-dict per stage, naming which concrete implementation ran and a short result — this is what the internal debug panel reads). The caller (`create_session`/`apply_feedback`/`advance_session`) adds the `vibe_understander` trace entry, persists the relevant `DJSession` columns, and `serialize_session` turns the row into the `SessionRead` Pydantic response. On the frontend, `normalizeSession` (`sessionApi.js`) converts that into the `Session` object the Svelte store and components consume.

---

## 3. The three caching layers

### a. Audius search cache — `app/services/audius_service.py`
- **What it caches:** the raw list-of-dicts result of one `search_tracks(prompt, limit)` call.
- **Key:** `(prompt, limit)` tuple — exact string + limit match only, no fuzzy matching.
- **TTL:** `AUDIUS_SEARCH_CACHE_TTL_SECONDS`, default **75 seconds**.
- **Bound:** `AUDIUS_SEARCH_CACHE_MAX_ENTRIES`, default **200**, oldest-first eviction (`_cache_put`).
- **Guard:** `_search_cache_lock` (a plain `threading.Lock`).
- Only successful, *non-empty* results are cached — an empty result is indistinguishable from "Audius has nothing" vs. "the call just failed," so caching it would let a transient hiccup poison that exact query string for the full TTL.
- This is the lowest-level, most general-purpose of the three: it's shared across *every* caller process-wide (any two different sessions, or a session and a Mix, asking the same literal query string within 75 seconds hit it), and it's what an individual query inside `MultiQueryAudiusRetriever.retrieve` goes through.

### b. Session candidate pool — `app/services/session_candidate_pool.py`
- **What it caches:** the full *ranked* `list[Track]` result of one `retrieve_candidates_with_fallback` call for one session.
- **Key:** `session_id` plus a `RetrievalFingerprint` — `(intent.artist, intent.artist_mode, tuple(sorted(intent.genres)), intent.mood, intent.energy)`, produced by `fingerprint_for(intent)`. Deliberately **excludes** `vocals` and `search_query`, since neither `build_queries` nor `_score_candidates` reads them — a vocals-only feedback change still hits this cache.
- **TTL:** `SESSION_CANDIDATE_POOL_TTL_SECONDS`, default **600 seconds**.
- **Bound:** `SESSION_CANDIDATE_POOL_MAX_ENTRIES`, default **500**, oldest-first eviction (`put`).
- **Guard:** module-level `_lock`.
- Consulted inside `session_manager._resolve_and_render` *before* calling the retriever at all: a hit is only actually used if it still has more than `_CANDIDATE_POOL_REFRESH_THRESHOLD` (3) not-yet-excluded candidates left — an almost-exhausted pool forces a real refresh rather than grinding down to repeats before the fingerprint next changes.

### c. `prepared_next_json` fast-path slot — `session_manager.py` + `DJSession.prepared_next_json`
- **What it "caches":** not a lookup cache in the traditional sense — a single-entry, per-session-row parked *complete resolution result*: `track_key`, `artist`, `now_playing`, `reasoning`, `pipeline_trace` (without a `vibe_understander` entry yet — that's added at consume time), plus the same kind of fingerprint as (b) — JSON-normalized to a list via `_fingerprint_as_json` (tuples don't survive a JSON round-trip) — and a `prepared_at` timestamp.
- **Key:** implicitly the `DJSession.id` (it's a column on that row), plus the fingerprint stored inside the blob, re-checked at consume time.
- **TTL:** `PREPARED_NEXT_TTL_SECONDS`, default **300 seconds**, checked by `_prepared_expired`.
- **Guard:** not a data-integrity lock — `_prepare_locks` (a `Lock`-per-session_id dict) exists purely to stop two near-simultaneous `prepare_next()` calls from both paying for a full retrieval/render; a race here is provably just wasted duplicate work, never corruption (see §6).
- Written only by `prepare_next`, consumed only by `advance_session`'s fast path (§5).

### How a write to one relates to the others
- **(a) is upstream of (b):** a cache miss on the session candidate pool means `_resolve_and_render` calls `retrieve_candidates_with_fallback`, which calls `MultiQueryAudiusRetriever.retrieve`, whose individual `search_tracks` calls may still hit (a) even when (b) misses.
- **(b) is upstream of (c):** `prepare_next()`'s real work is itself a call to `_resolve_and_render`, which checks (b) first — so a `prepare_next()` call can be nearly free if (b) is warm, and its *side effect* of a (b) miss is a fresh `session_candidate_pool.put()`, populating (b) even though the caller only asked for (c).
- **(c) sits in front of both:** a valid (c) hit in `advance_session` skips (b) and (a) and the entire retrieve/select/plan/render pipeline outright — no candidate lookup happens at all.
- **Invalidation is independent per layer:** (a) only ever expires by TTL/eviction, never explicitly cleared by session logic. (b) is invalidated by fingerprint mismatch (any feedback that changes energy/genre/mood/artist naturally misses, since that's exactly what the fingerprint tracks) or by the freshness-threshold check described above — no explicit "clear" call exists for it. (c) is invalidated by fingerprint mismatch **and** TTL **and** three explicit clears (`apply_feedback` when intent mutates, `stop_session`, and self-clearing immediately after a fast-path consume) — see §5 for the complete list.

---

## 4. The guardrail mechanism (LLM containment)

The LLM (Ollama, via `prompt_parser.parse_prompt`) is only ever asked to *classify*, never to choose a track or generate freeform output that gets used directly. The containment happens in two places:

**What the LLM is asked for.** `parse_prompt` sends a JSON-schema-constrained request — `"format": PromptIntent.model_json_schema()` — so Ollama's own decoding is structurally constrained to the `PromptIntent` shape, not just instructed to "return JSON." The prompt text asks it to classify mood/energy/vocals/up to 5 genres/an optional artist+mode/a search_query.

**What actually survives: `_apply_guardrails(intent, fallback)`.** This is the exact function that "confines an LLM's structured guess to refining classification only" (its own docstring), and it's called unconditionally on every successful Ollama response before that response is used:

- `intent.genres` is filtered down to only values already in `ALLOWED_GENRES` (a fixed 11-entry set) — anything the LLM invents outside that set is silently dropped, never passed to retrieval.
- `intent.search_query = fallback.search_query` — this line **unconditionally overwrites** whatever `search_query` the LLM returned with the deterministic parser's own value (the raw user prompt, lowercased and whitespace-normalized). This is the specific line that prevents "the LLM invents search text": the LLM's own `search_query` field is discarded outright, every time, regardless of what it said.
- Artist resolution is regex-first: if `fallback.artist` (extracted by `deterministic_parse` → `_extract_artist_and_mode`, a pure-regex pass over the raw prompt with no LLM involvement) is truthy, both `intent.artist` **and** `intent.artist_mode` are overwritten with the regex-extracted values — the LLM's artist guess is discarded entirely. Only when the regex found *nothing* does the LLM's own artist string get used (its `artist_mode` was already constrained to one of the three literal values by Pydantic when the response was parsed).

The net effect: the LLM can nudge mood/energy/vocals/genre classification, and can supply an artist name only as a fallback when the deterministic regex found none — it can never pick which literal search string reaches Audius, and it never sees or touches the actual candidate `Track` objects at all (that happens entirely downstream, in `audius_retriever.py`, on real API data).

**Degradation when Ollama fails, times out, or returns garbage.** All of the following collapse to the exact same outcome — `return fallback`, i.e. the deterministic parse alone, functionally identical to `VIBE_LLM_PROVIDER=none`:

- A required-artist prompt (`fallback.artist_mode == "required"`) never calls Ollama at all — `query_planner.build_queries` already prioritizes the artist alone regardless of any further refinement, so the call would be "pure wasted latency" (comment in `parse_prompt`).
- `OLLAMA_BASE_URL`/`OLLAMA_MODEL` unset → returns `fallback` immediately, no attempt made.
- `_ollama_slots` (a `BoundedSemaphore`, size `OLLAMA_MAX_CONCURRENCY`, default 4) is fully checked out → `_ollama_slots.acquire(timeout=0.05)` fails fast, returns `fallback` — no queueing, no blocking a request behind another one's Ollama call.
- The HTTP call itself is wrapped in `try/except (httpx.HTTPError, ValueError, TypeError, ValidationError)` — network errors, non-JSON bodies, and a response that fails `PromptIntent.model_validate` (wrong types, a genre/mode outside the allowed literals, etc.) all fall into the same `except` and return `fallback`.
- A `finally` block always records the attempt's latency and success/failure (`_record_ollama_call`) for the debug panel, regardless of which of the above paths was taken.
- `OLLAMA_TIMEOUT_SECONDS` (default 3.0, clamped to 0.5–20.0) bounds how long a single call is allowed to hang before it's treated as a failure.

So the worst case for a completely broken Ollama deployment is: every session runs on deterministic classification only, with a bounded (≤20s) worst-case delay per request rather than an unbounded hang or a 500.

---

## 5. The `prepare_next` / `advance_session` fast path

**The one validation function that decides everything:** `session_manager._prepared_is_valid(prepared, fingerprint)`.

```
if prepared is None: False
if prepared["fingerprint"] != _fingerprint_as_json(fingerprint): False
else: not _prepared_expired(prepared)   # time.monotonic() - prepared["prepared_at"] < PREPARED_NEXT_TTL_SECONDS
```

`advance_session` calls this with `intent = PromptIntent.model_validate(session.intent_json)` (the session's **current**, possibly-feedback-mutated intent, read fresh at the top of the function) and `fingerprint = session_candidate_pool.fingerprint_for(intent)` computed from it — never from whatever intent was active when the item was prepared. This is deliberate: feedback can land in the gap between a `prepare_next()` completing and the eventual `advance()` consuming it, and the fingerprint check is what catches that.

If valid: `advance_session` applies `prepared["now_playing"]`/`["reasoning"]`/`["pipeline_trace"]` directly (patching in a fresh `vibe_understander` trace entry, since the parked one deliberately never had one — see §3c), reads `retriever_name` back out of the prepared `pipeline_trace["candidate_retriever"]["name"]` rather than needing a separate stored field, appends to the played-history lists, **clears `prepared_next_json` to `None`**, commits, and returns — `retrieve_candidates_with_fallback`, `selector.select`, `planner.plan`, and `renderer.render` are never called.

If invalid (any reason): falls through to exactly the pre-fast-path code — a fresh `_resolve_and_render` call, unchanged from what `advance_session` always did.

**Every place a prepared item can become invalid or get cleared:**

1. **Fingerprint mismatch** (implicit, checked every time) — any change to `intent.artist`, `intent.artist_mode`, `intent.genres`, `intent.mood`, or `intent.energy` between prepare-time and consume-time. This is the primary defense; everything else is either redundant-on-purpose or handles a case the fingerprint can't.
2. **TTL expiry** (implicit) — `PREPARED_NEXT_TTL_SECONDS` (default 300s) elapsed since `prepared_at`. Nothing actively purges an expired entry; it just gets treated as invalid the next time it's checked, and will eventually be overwritten by a new prepare or explicitly cleared.
3. **`apply_feedback`, explicit clear** — `if mutated is not current_intent: session.prepared_next_json = None`, inside the success branch of a real re-resolution. Gated specifically on the intent *object* actually changing (true for "More energy"/"Less vocals"/"reinforce" with different values), **not** on `prefers_smoother` alone — "Smoother" feedback leaves the intent (and so the fingerprint) unchanged, so a still-fingerprint-matching prepared item legitimately survives it. This is explicitly described in the code as belt-and-suspenders on top of #1, matching the source design note "MORE ENERGY → discard the prepared next item."
4. **`stop_session`, explicit clear** — unconditional `session.prepared_next_json = None` when the session stops, so a stopped session doesn't hold a prepared item nobody will ever consume.
5. **`advance_session`'s own fast-path consumption** — clears it to `None` immediately after applying it, in the same commit, so it can never be served twice.
6. **`prepare_next` itself refuses to clobber a still-valid item** — before doing any retrieval work, it runs the same `_prepared_is_valid` check against the *current* fingerprint and no-ops if already valid. This isn't invalidation, but it's the reason calling `prepare-next` twice in a row doesn't do redundant work or overwrite a good pending item with a possibly-worse one.

A new `DJSession` row (`create_session`) simply never has this field set, so it starts `None` — no explicit clear needed there.

---

## 6. Concurrency model

**Every module-level cache/lock in this loop's direct path:**

| File | Lock | Guards |
|---|---|---|
| `audius_service.py` | `_search_cache_lock` | `_search_cache: dict[(prompt,limit) -> (expires_at, results)]` |
| `audius_service.py` | `_last_cache_lookup_lock` | `_last_cache_lookup: {"hit": bool\|None}` (debug-panel only) |
| `prompt_parser.py` | `_ollama_slots` (`BoundedSemaphore`, not a `Lock`) | limits concurrent outbound Ollama calls, doesn't guard a data structure |
| `prompt_parser.py` | `_last_call_lock` | `_last_ollama_call: dict` (debug-panel only) |
| `session_candidate_pool.py` | `_lock` | `_pools: dict[session_id -> (fingerprint, tracks, cached_at)]` |
| `session_manager.py` | `_prepare_locks_guard` | `_prepare_locks: dict[session_id -> Lock]` (a lock guarding the *creation* of per-session locks, not the prepare work itself) |

Additionally, `MultiQueryAudiusRetriever`/`AudiusCandidateRetriever` (`audius_retriever.py`) hold `self.last_candidate_scores`/`self.last_cache_hit` as plain **instance** attributes on a process-wide singleton (bound once in `dependencies.py`) — not guarded by any lock at all, and explicitly documented in-code as debug-only, best-effort state that can show another concurrent request's data under a race.

**What a race between two concurrent requests can do:**
- Two requests touching the *same* `DJSession` row (e.g. a `prepare-next` and an `advance` landing close together) each get their own SQLAlchemy `Session` (one per request, via `Depends(get_db)`) and their own in-memory copy of the row. Both can write independently; whichever commits **last** wins — `advance_session`'s own docstring states this outright as the accepted behavior, no special row-locking is used.
- Two `prepare_next()` calls for the same session: the per-session `Lock` means only one does real work at a time; the other's `lock.acquire(blocking=False)` fails immediately and it returns as a no-op.
- Two `search_tracks()` calls for the same `(prompt, limit)` racing a cold cache: both can miss simultaneously (the get-then-put isn't atomic across the two lock acquisitions) and both hit the real Audius API — wasted duplicate network work, not corruption; the later `_cache_put` simply overwrites.
- Two writers to `session_candidate_pool._pools[session_id]`: `put()` is internally lock-guarded, so the dict is never structurally corrupted; whichever `put()` runs last just overwrites the cached tuple for that key.

**What a race cannot do:**
- Cannot structurally corrupt any of the four `Lock`-guarded dicts (Python dict mutation under a held `Lock` is fully serialized).
- Cannot make `advance_session`'s fast path apply a stale prepared item — validity is re-derived from the row's *current* `intent_json* at the exact moment of the check, never cached or assumed from an earlier read.
- Cannot let one session's caches affect another's — `session_candidate_pool` and `_prepare_locks` are both keyed by `session_id`.
- Cannot leave `prepared_next_json` half-written from another request's point of view — it's built as one Python dict literal and committed as a single transaction, so a concurrent reader sees either the whole old value or the whole new one (ordinary DB transaction semantics, not anything the Python-level locks provide).

**Why this is sufficient here:** every one of these is a plain in-process `threading.Lock`/`BoundedSemaphore`, not a distributed lock (Redis, etc.) — a deliberate, load-bearing assumption that this runs as a **single backend worker process**. There's exactly one Python process's memory to reason about. Every cache here is also explicitly documented as "a miss always falls through to a real call," so even the un-prevented races (cache stampedes, last-write-wins on a session row) degrade to *wasted work or slightly stale-but-still-correct-shaped data*, never to a crash or corrupted session state. If this were ever run with multiple worker processes, each would hold entirely separate copies of all four caches — still correct (nothing here depends on cross-process coherency), just less effective (a warm cache in one process doesn't help a request landing in another).

---

## 7. The frontend loop

**State machine (`sessionStore.js`).** `status` is one of `APP_STATES`: `IDLE`, `STARTING`, `PLAYING`, `BUFFERING_NEXT`, `STOPPED`, `ERROR` (`frontend/src/lib/constants/appStates.js`). Observed transitions:

- `IDLE → STARTING`: `start()` called with a non-blank prompt.
- `STARTING → PLAYING`: `apiStartSession` resolves with a session that has playable audio.
- `STARTING → ERROR`: `apiStartSession` throws, or the resolved session lacks any playable `audioUrl`.
- `PLAYING → STOPPED`: `stop()` resolves successfully.
- `PLAYING → STARTING`: calling `start()` again with a new prompt while already playing (`abortPendingRequests()` cancels every in-flight request first).
- `ERROR → IDLE`-equivalent: `reset()` bumps both version counters, aborts everything, and resets to `initialState()`.
- **`status` stays `PLAYING`** throughout `advance()`/`sendFeedback()`/`prepareNext()` cycles — none of them transition `status`; the "something is happening" signal is the separate `isFeedbackPending`/`isPlaybackBuffering` booleans instead.

**Why `advance()`, `sendFeedback()`, and `prepareNext()` share `feedbackVersion`.** All three do the same dance: `const requestVersion = ++feedbackVersion` before awaiting their network call, then after it resolves, check `requestVersion !== feedbackVersion || latestState.session?.id !== sessionId || lifecycleAtRequest !== lifecycleVersion` and silently discard their own result (return `false`/`null`) if any of those moved. They share the counter because these three calls are semantically mutually exclusive on a single session — only the *most recent* one's answer should ever be applied. If a user sends coaching feedback while an `advance()` (or a speculative `prepareNext()`) is still in flight, that bumps `feedbackVersion`, so the earlier call's eventual result — even if it arrives and resolves without error — is recognized as stale and thrown away; explicit coaching always wins over an automatic continuation. They also share the single `feedbackController` `AbortController` variable: each new call overwrites it with a fresh controller, so `stop()` (`feedbackController?.abort()`) always cancels whichever of the three most recently claimed the slot — an earlier, already-superseded call's underlying `fetch` may still be physically in flight in the background, but its result is inert once it lands, caught by the version check.

`lifecycleVersion` is the outer, coarser version — bumped only by `start()` and `reset()`, meaning "an entirely new session, not just a new resolution within the current one." All three `feedbackVersion`-sharing calls also snapshot and re-check `lifecycleVersion`, so a stray result from a *previous* session can never apply itself after the user has already started a new one, even if `feedbackVersion` alone would have looked consistent.

`prepareNext()` (`sessionStore.js`) is deliberately lighter than the other two: on success it does **not** call `update()` to change any session state (the backend already persisted the prepared item server-side; there's nothing new to reflect in the UI), and any failure is swallowed silently rather than surfaced as a user-facing error — unlike `advance`/`sendFeedback`, a failed `prepareNext()` just means "no speedup this cycle."

**When `DJPlayerCard.svelte` decides to call it.** `syncTimeline()` — the `<audio>` element's `ontimeupdate` handler — calls `maybePrepareNext(bounds)` on every tick. That function is a no-op if: there's already a next *local* segment queued (`hasNext`, meaning the upcoming transition doesn't need a backend call at all — see `handleAudioEnded`'s `hasNext ? changeSegment(1) : onMediaEnded()`); it's already fired for this exact `audioUrl` (tracked via the local `preparedForUrl` flag, reset by a dedicated `$effect` whenever `audioUrl` changes); or the segment has zero length. Otherwise it computes `remaining = bounds.length - currentTime` against a **percentage-based** threshold, `Math.max(10, bounds.length * 0.1)` — at least 10 seconds, or 10% of the segment's length, whichever is larger, specifically so this fires sensibly on both a ~45-second catalog demo clip and a multi-minute Audius track rather than using one fixed second count. Once past that threshold, it immediately sets `preparedForUrl = audioUrl` (before the network call even starts, so rapid subsequent ticks don't re-fire) and calls `onPrepareNext()` (wired to `sessionStore.prepareNext`). If it resolves with a URL and the segment hasn't changed in the meantime, that URL is stashed in `preloadAudioUrl`, which renders a second, hidden `<audio preload="auto">` element purely to give the browser a head start on the bytes — it is never wired into actual playback; the real swap only happens through the normal `advance()` → new `audioUrl` path.

---

## 8. Observations

Purely descriptive — nothing below was acted on.

1. **`BUFFERING_NEXT` is defined but never reached.** `frontend/src/lib/constants/appStates.js` defines `APP_STATES.BUFFERING_NEXT`, and `+page.svelte` checks for it in `isSessionActive`/`canChangeVibe`, but `sessionStore.js` never actually sets `status` to that value anywhere — "buffering" during advance/feedback/prepare is represented entirely through the separate `isPlaybackBuffering` boolean instead, so those two `+page.svelte` branches are currently unreachable via that particular status check.

2. **One of three same-shaped module caches has no eviction bound.** `audius_service._search_cache` and `session_candidate_pool._pools` both grow one entry per distinct key and are explicitly bounded (`AUDIUS_SEARCH_CACHE_MAX_ENTRIES` / `SESSION_CANDIDATE_POOL_MAX_ENTRIES`, oldest-first eviction). `session_manager._prepare_locks` (new with the `prepare_next` fast path) follows the identical "one entry per session_id, created on first use, never removed" shape, but has no equivalent bound — it grows by one `Lock` object per distinct session ever created in this process's lifetime.

3. **The "apply a resolution to a session" bookkeeping is hand-written three times.** Setting `now_playing_json`/`reasoning_json`/`pipeline_trace_json`/`retriever_name`, falling back `vibe_label = X or session.vibe_label`, and appending+capping both `played_track_keys_json` and `played_artists_json` is written out nearly verbatim in `apply_feedback`'s success branch, `advance_session`'s slow path, and `advance_session`'s fast path — three close copies of the same sequence.

4. **The `pipeline_trace["vibe_understander"]` block is hand-written four times** — in `create_session`, `apply_feedback`, and both branches of `advance_session` — each building the same `{"implementation", "invoked", "intent", "original_intent"}` shape with slightly different `invoked`/`intent` values.

5. **The crossfade math is computed on every resolution but never audible in a live session.** `TransitionPlanner.plan` (`transition_planner.py`) runs every time and its output lands in `reasoning.transitionPlan` and the debug trace, but `session_manager._resolve_and_render` always calls `renderer.render([segment], [transition])` with exactly one segment — `PydubAudioRenderer._render_composite`, the only code path that actually crossfades audio together, is only ever reached from the separate Mixes feature (`mix_service.py`), never from the session loop. The transition text a user reads is real math, but doesn't currently change the audio they hear.

6. **No HTTP connection reuse across the retrieval fan-out.** `audius_service._search_tracks_uncached` opens a fresh `httpx.Client()` per call, so a multi-round retrieval's several sequential Audius searches (and the eventual track download in `audio_renderer._download`) each pay for their own connection setup rather than sharing a keep-alive connection.

7. **Duration parsing is duplicated across two files.** `audius_service._search_tracks_uncached` and `audius_retriever._to_track` both independently do `max(0, int(item.get("duration") or 0))` wrapped in `except (TypeError, ValueError)`. For real Audius traffic, the second parse is operating on data that already passed through the first — defensive-in-depth rather than a functional gap.

8. **`prepared_next_json`'s timestamp uses `time.monotonic()`, but unlike its sibling cache, it's persisted to the database.** `session_candidate_pool.py` also timestamps with `time.monotonic()`, but that cache is purely in-memory and lost on every restart anyway, so a process-relative clock is harmless there. `prepared_next_json` is a DB column — `time.monotonic()`'s zero point is specific to the process that wrote it, so a value written just before a backend restart and read just after would be comparing against a very different reference point. This would only matter inside the narrow `PREPARED_NEXT_TTL_SECONDS` (300s) window before some other invalidation (a new prepare, a feedback call, a stop) overwrote or cleared it anyway.

9. **The catalog fallback never actually uses the diversity signal it accepts.** `CatalogTrackRetriever.retrieve` (`catalog_retriever.py`) takes `recent_artists` for interface compatibility but immediately does `del recent_artists`, since it has no ranking stage to feed it into — session-aware artist-repeat avoidance only takes effect when Audius (not the local catalog fallback) is the one serving candidates.

---

*Generated by a read-only review pass; no source file listed in the task scope was modified.*
