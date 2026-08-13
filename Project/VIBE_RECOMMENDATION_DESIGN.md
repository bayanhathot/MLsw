# Vibe Recommendation Design: Multi-Query Metadata Ranking

**Status:** proposed, not yet implemented.
**Scope:** replaces how `AudiusCandidateRetriever` turns a `PromptIntent` into ranked candidates. Nothing else in the pipeline changes.
**Out of scope (deliberately deferred):** semantic/embedding retrieval, BPM/key-based ranking, a vector store. See "Why this scope" below.

---

## 1. Problem this solves

A user describes a vibe ("chill lofi beats for late night coding") instead of naming a track or artist. Today that fails in a specific, traceable way:

1. `prompt_parser.deterministic_parse` classifies it into `genres=["lofi"]`, `energy="low"`, etc. — this part already works.
2. But `AudiusCandidateRetriever.retrieve` (`backend/app/services/pipeline/audius_retriever.py:21`) searches Audius with `intent.artist or intent.search_query` — and `intent.search_query` is always the raw sentence, because `prompt_parser._apply_guardrails` (`prompt_parser.py:119`) unconditionally overwrites it with `fallback.search_query` even when an LLM ran.
3. Audius's search endpoint is literal/keyword, not semantic. A full sentence often returns zero hits (verified: `"lofi chill"` → real hits, `"chill lofi beats for late night coding"` → zero).
4. Zero Audius hits triggers the fallback: `CatalogTrackRetriever`, which is 4 seeded rows matched by crude substring checks (`catalog_retriever.py:75-87`) that never look at `intent.genres` either.

Net effect: `intent.genres` and `intent.mood` — the actual structured vibe — are computed and then never used by anything. This design fixes that by making them the primary retrieval signal, without touching the no-hallucination guarantee described in section 3.

---

## 2. Why this scope (and not the full hybrid-semantic design)

A fuller design (semantic embeddings, a vector-indexed catalog, BPM/key-aware session ranking) was evaluated and rejected **for now**, for two concrete reasons, not just "less is more":

- **`SegmentSelector` never has BPM/key for Audius tracks.** `segment_selector.py:22-51` only reads cached `bpm`/`musical_key` when `track.catalog_track_id is not None`; every Audius track falls through to `bpm=None, musical_key=None`. That data comes from `audio_analysis.py`'s one-time librosa job, which requires the audio file already downloaded to local disk — it only runs for uploaded catalog tracks. A ranker that scores BPM/key compatibility across 30-60 live-fetched Audius candidates would need to download and analyze all of them first, which is a second heavy pipeline this design doesn't need.
- **Course scope (`feedback.md`):** this project already owes a forum with DMs/live notifications, a parallel job queue, local-LLM concurrency handling, CI/CD, and Azure deployment. "Robustness to hallucinations" is worth 10 rubric points and is already satisfied structurally by the guardrail in section 3. A production-grade hybrid recommender is good engineering but not points-efficient right now.

This design only uses data that already exists in the repo: `PromptIntent.genres/mood/energy/vocals/artist`, Audius's own search results, and `DJSession.played_track_keys_json`. No new infrastructure (embedding model, vector DB, audio download-and-analyze step) is required.

---

## 3. Safety boundary (unchanged, restated for this design)

Same rule as today, from `prompt_parser.py`'s module docstring: **the LLM may classify, it may never select or invent a track.** Concretely, in this design:

- The LLM (when a model is loaded — see section 8) only ever produces `mood`, `energy`, `vocals`, `genres` (filtered to `ALLOWED_GENRES`, 11 words, `prompt_parser.py:24-36`), and `artist`.
- `QueryPlanner` (new, section 4.2) builds search strings **deterministically** from those already-whitelisted fields. It does not accept or forward LLM freeform text as a query.
- Every returned `Track` still only ever comes from a real Audius search hit or a real `CatalogTrack` row (`CandidateRetriever.retrieve`'s existing contract, `interfaces.py:23-34`: "An empty list means nothing matched closely enough — callers must report that plainly rather than substitute an unrelated candidate").

Nothing in `_apply_guardrails` needs to change for this design. It stays exactly as-is.

---

## 4. Pipeline

```
PromptIntent (existing, unchanged)
        |
        v
   QueryPlanner                  <- NEW
        |
        v
MultiQueryAudiusRetriever        <- NEW, replaces AudiusCandidateRetriever
   |    |
   |    +-- fan out N queries to audius_service.search_tracks
   |    +-- retry/relax ladder if a round returns weak results
   |    +-- RRF fusion + dedup across the query result lists
   |    +-- MetadataCandidateRanker (genre/mood/energy/retrieval-confidence)
   |    +-- returns ordered list[Track], same as today
   v
CatalogTrackRetriever             <- UNCHANGED (fallback, only on empty)
        |
        v
_resolve_and_render's existing exclude-scan   <- UNCHANGED (session diversity/history, already works)
        |
        v
SegmentSelector -> TransitionPlanner -> AudioRenderer   <- UNCHANGED
```

The key architectural point: **`MultiQueryAudiusRetriever` implements the exact same `CandidateRetriever` interface as today's `AudiusCandidateRetriever`.** Everything downstream of `retriever.retrieve(db, intent, limit=5)` — `orchestrator.py`, `session_manager.py`, the fallback-to-catalog logic, the recently-played exclusion — does not need to change at all. This is a swap-in, not a rewrite.

---

## 5. New components

### 5.1 `QueryPlanner`

**File:** `backend/app/services/pipeline/query_planner.py` (new)

**Contract:**
```python
def build_queries(intent: PromptIntent, *, max_queries: int = 5) -> list[str]:
    ...
```

Pure function, no I/O, fully unit-testable. Priority order (stops adding once `max_queries` is reached):

1. **Artist, if set** (`intent.artist`) — highest priority, exact as today's behavior. This also transparently fixes the "bare artist name gets missed" issue from earlier: once a model is loaded, `_apply_guardrails` already lets the LLM's artist guess win when the deterministic regex finds nothing (`prompt_parser.py:120-121`), so a plain "play george wassouf" starts producing `intent.artist` once the LLM runs — `QueryPlanner` just has to use it, which it does here first.
2. **Genre pairs**: for `intent.genres` (already filtered to the 11-word whitelist), emit one query per genre, and one combined query if there are 2+ genres (e.g. `"lofi"`, `"lofi chill"`).
3. **Mood + energy**: one query combining `intent.mood` with an energy adjective (`"chill lofi"`, `"high energy techno"`) — only if it wouldn't just duplicate a genre query already added.
4. **Raw sentence, last resort**: `intent.search_query` (the existing guardrail-protected raw prompt) — kept as the final fallback query, exactly so nothing regresses for prompts that don't cleanly map to a genre.

```python
def build_queries(intent: PromptIntent, *, max_queries: int = 5) -> list[str]:
    queries: list[str] = []

    def add(q: str) -> None:
        q = q.strip()
        if q and q.lower() not in (existing.lower() for existing in queries):
            queries.append(q)

    if intent.artist:
        add(intent.artist)
    for genre in intent.genres:
        add(genre)
    if len(intent.genres) >= 2:
        add(" ".join(intent.genres[:2]))
    if intent.mood and intent.mood != "balanced":
        add(f"{intent.mood} {intent.genres[0]}" if intent.genres else intent.mood)
    add(intent.search_query)

    return queries[:max_queries]
```

No network calls, no LLM calls — this only rearranges data already present on `intent`.

### 5.2 `MultiQueryAudiusRetriever`

**File:** `backend/app/services/pipeline/audius_retriever.py` (extend in place, or add alongside — see section 6)

Replaces the single `search_tracks(query, limit)` call with:

```python
class MultiQueryAudiusRetriever(CandidateRetriever):
    name = "audius_multi_query"

    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
        queries = build_queries(intent, max_queries=MAX_QUERIES)
        pool: dict[str, Track] = {}          # keyed by f"{source}:{source_track_id}"
        rank_lists: list[list[str]] = []      # one ranked key-list per query, for RRF

        for round_queries in _relaxation_rounds(queries):
            for query in round_queries:
                raw = search_tracks(query, limit=CANDIDATES_PER_QUERY)
                keys = []
                for item in raw:
                    track = _to_track(item)          # same mapping as today's _to_track logic
                    if track is None:
                        continue
                    key = f"{track.source}:{track.source_track_id}"
                    pool[key] = track
                    keys.append(key)
                if keys:
                    rank_lists.append(keys)
            if len(pool) >= MIN_POOL_SIZE:
                break  # enough candidates, stop relaxing

        if not pool:
            return []

        fused_order = _reciprocal_rank_fusion(rank_lists)          # section 5.3
        ranked = _rank_by_metadata(pool, fused_order, intent)      # section 5.4
        return [pool[key] for key in ranked[:limit]]
```

`_to_track` is the existing per-item mapping logic from today's `audius_retriever.py:37-53`, unchanged — just factored so both the old and new retriever can share it if you keep both around during rollout.

**Retry/relax ladder (`_relaxation_rounds`):** `build_queries` already returns queries ordered specific-to-general. Round 1 tries the first 2 (most specific); if the combined pool across all queries tried so far is still under `MIN_POOL_SIZE` (e.g. 5), round 2 adds the next 2, and so on, up to `MAX_RETRIEVAL_ROUNDS` (e.g. 3). This directly replaces the current single-shot "one sentence, zero results, fall through to catalog" failure mode with "try narrower queries first, broaden only if needed" — using the *same* Audius call, just more of them.

### 5.3 Reciprocal Rank Fusion

Plain function, no external dependency:

```python
def _reciprocal_rank_fusion(rank_lists: list[list[str]], *, k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranked_keys in rank_lists:
        for position, key in enumerate(ranked_keys):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=lambda key: scores[key], reverse=True)
```

This is what "candidate fusion + dedup" reduces to here: a track that shows up near the top of *multiple* query result lists outranks one that only appeared once, without needing to compare Audius's own internal relevance score (which isn't returned/comparable anyway) against anything else.

### 5.4 `MetadataCandidateRanker`

Re-ranks the RRF-fused order using the structured intent, since RRF alone only reflects "how findable was this," not "does it actually match the vibe."

```python
def _rank_by_metadata(
    pool: dict[str, Track], fused_order: list[str], intent: PromptIntent
) -> list[str]:
    rrf_rank = {key: i for i, key in enumerate(fused_order)}
    n = len(fused_order)

    def score(key: str) -> float:
        track = pool[key]
        retrieval_score = 1.0 - (rrf_rank[key] / max(n - 1, 1))     # 0..1, higher = better
        genre_score = 1.0 if track.genre and track.genre.lower() in {g.lower() for g in intent.genres} else 0.0
        mood_score = 1.0 if track.vibe and intent.mood and track.vibe.lower() == intent.mood.lower() else 0.0
        energy_score = _genre_energy_match(track.genre, intent.energy)  # section "known limitations"

        return (
            WEIGHT_RETRIEVAL * retrieval_score
            + WEIGHT_GENRE * genre_score
            + WEIGHT_MOOD * mood_score
            + WEIGHT_ENERGY * energy_score
        )

    return sorted(pool.keys(), key=score, reverse=True)
```

All four sub-scores are normalized to `0..1` before weighting (this is the normalization step the earlier all-semantic design was missing) — a hand-tuned weight then means what it says, instead of being dominated by whichever raw signal happens to have the widest range. `WEIGHT_*` constants live in config (env-overridable), matching the pattern `ARTIST_MATCH_THRESHOLD` already uses in `catalog_retriever.py:33`.

### 5.5 Session diversity/history — no new code required for the MVP

This is already implemented and already runs on every candidate list, retriever-agnostic: `_resolve_and_render` in `session_manager.py:174-180` does

```python
track = next(
    (candidate for candidate in candidates if _track_key(candidate) not in exclude_track_keys),
    candidates[0],
)
```

against whatever ordered list `retriever.retrieve()` returns. Today Audius only returns up to 5 candidates from one query, so there's rarely a fresh one to fall through to. Because `MultiQueryAudiusRetriever` returns a richer, better-ranked list (built from `CANDIDATES_PER_QUERY x len(queries)` raw hits, deduped and ranked down to `limit`), this exclude-scan gets meaningfully more real alternatives to skip to — diversity improves as a side effect of a bigger candidate pool, with zero changes to `session_manager.py`.

**Optional phase-2 enhancement, not required now:** extend `CandidateRetriever.retrieve` to accept an optional `exclude: frozenset[str] = frozenset()` so the ranker can treat "already played" as a scored penalty instead of a post-hoc skip, and so `MultiQueryAudiusRetriever` could requery when everything fresh is exhausted. This is a backward-compatible default-parameter change (`CatalogTrackRetriever` wouldn't need to change at all unless you want it to use it too) — worth doing later, not blocking for the vibe-description fix itself.

---

## 6. File-by-file integration plan

| File | Change |
|---|---|
| `backend/app/services/pipeline/query_planner.py` | **New.** `build_queries(intent, max_queries)`. Pure function, no dependencies beyond `app.schemas.PromptIntent`. |
| `backend/app/services/pipeline/audius_retriever.py` | **Extend.** Add `MultiQueryAudiusRetriever` class (keep the existing `AudiusCandidateRetriever` in place, at least during rollout — see section 8). Factor `_to_track` out of the old class so both can call it. Add `_reciprocal_rank_fusion`, `_rank_by_metadata`, `_relaxation_rounds` as module-level functions or a small `ranking.py` sibling if the file gets long. |
| `backend/app/services/pipeline/dependencies.py` | **One line.** In `_build vibe/candidate singletons` section (`dependencies.py:72`): `_audius_retriever = AudiusCandidateRetriever()` → `_audius_retriever = MultiQueryAudiusRetriever()` (or gate by env var — section 8). Nothing else in this file changes: `get_session_candidate_retriever`, `get_mix_candidate_retriever`, `get_catalog_candidate_retriever` all keep returning what they already return. |
| `backend/app/services/pipeline/interfaces.py` | **Unchanged.** `CandidateRetriever.retrieve(db, intent, *, limit=5) -> list[Track]` already covers this. |
| `backend/app/services/pipeline/orchestrator.py` | **Unchanged.** `retrieve_candidates_with_fallback` already does primary-then-catalog-fallback with the "report plainly on empty" contract this design relies on. |
| `backend/app/services/session_manager.py` | **Unchanged** for the MVP (section 5.5). Only touch this if you do the phase-2 `exclude`-aware retrieval enhancement. |
| `backend/app/services/pipeline/catalog_retriever.py` | **Unchanged.** Still the safety-net fallback for when even multi-query Audius comes back empty. (Optional future improvement: make `_mood_bucket_for` read `intent.genres` too — same idea as this whole design, applied to the 4-row fallback. Not required now since it's rarely hit once Audius actually returns matches.) |
| `backend/app/core/config.py` (or wherever env-driven constants live today, alongside `ARTIST_MATCH_THRESHOLD`) | **New constants:** `MAX_QUERIES`, `CANDIDATES_PER_QUERY`, `MIN_POOL_SIZE`, `MAX_RETRIEVAL_ROUNDS`, `RRF_K`, `WEIGHT_RETRIEVAL`, `WEIGHT_GENRE`, `WEIGHT_MOOD`, `WEIGHT_ENERGY` — all env-overridable with sane defaults, same pattern as `ARTIST_MATCH_THRESHOLD = float(os.getenv(...))`. |
| `backend/tests/test_pipeline.py` | **New tests**, see section 9. |

Nothing in `prompt_parser.py`, `schemas.py`, `routers/`, or the frontend needs to change for this design. `intent.search_query` keeps meaning exactly what it means today.

---

## 7. Suggested defaults (all env-overridable)

```
MAX_QUERIES = 5
CANDIDATES_PER_QUERY = 5      # matches existing AudiusCandidateRetriever's default limit
MIN_POOL_SIZE = 5             # stop relaxing once the fused pool has at least this many
MAX_RETRIEVAL_ROUNDS = 3
RRF_K = 60                    # standard RRF constant
WEIGHT_RETRIEVAL = 0.4
WEIGHT_GENRE = 0.3
WEIGHT_MOOD = 0.15
WEIGHT_ENERGY = 0.15
```

Treat these as starting points to hand-tune against the evaluation prompts in section 10, not final values.

---

## 8. Rollout / feature flag

Mirror the existing `VIBE_LLM_PROVIDER` pattern (`dependencies.py:44`) so this can be toggled without a code change and without risking the currently-working artist/catalog paths:

```python
def _build_audius_retriever() -> CandidateRetriever:
    mode = os.getenv("AUDIUS_RETRIEVER", "multi_query").strip().lower()
    if mode == "multi_query":
        return MultiQueryAudiusRetriever()
    if mode == "single_query":
        return AudiusCandidateRetriever()
    raise RuntimeError(f"Unknown AUDIUS_RETRIEVER={mode!r}; expected 'multi_query' or 'single_query'.")
```

This means if the multi-query path ever behaves worse in practice (e.g. Audius rate-limits multiple calls per request), it's a one-env-var rollback, not a revert.

---

## 9. Testing plan

Following the existing conventions in `backend/tests/test_pipeline.py` (pytest, `monkeypatch`, no real network calls):

- **`build_queries` (pure function, no mocking needed):** artist-present case puts artist first; multi-genre case includes the combined pair; raw `search_query` is always last; `max_queries` truncates; duplicate queries (e.g. mood happens to equal a genre) are deduped.
- **`_reciprocal_rank_fusion`:** a key appearing top-of-list in two rank lists outranks a key appearing once; empty input returns empty output; single-list input preserves that list's order.
- **`_rank_by_metadata`:** a track whose genre is in `intent.genres` outranks an equally-RRF-ranked track whose genre isn't (isolate this by holding RRF rank constant across two fake tracks).
- **`MultiQueryAudiusRetriever.retrieve`, end-to-end with `monkeypatch.setattr(audius_retriever, "search_tracks", fake_search_tracks)`:** feed a `fake_search_tracks` that returns different results per query string, assert the final list is deduped by `source_track_id`, respects `limit`, and that a completely-empty Audius (`fake_search_tracks` always returns `[]`) still returns `[]` cleanly (so `retrieve_candidates_with_fallback` correctly falls through to `CatalogTrackRetriever`, per the existing test pattern in `test_catalog_retriever_*`).
- **Relaxation ladder:** `fake_search_tracks` returns 0 results for the first 2 (most specific) queries and real results for a later, broader one — assert the retriever still finds it within `MAX_RETRIEVAL_ROUNDS` and stops calling once `MIN_POOL_SIZE` is hit (assert on call count, not just the result).
- **Regression check:** re-run the existing `test_deterministic_artist_extraction_handles_common_phrasings` style prompts through the full `create_session` flow and confirm named-artist requests still resolve to that artist first (this design must not change today's working artist-search path).

---

## 10. Manual evaluation set

Once built, run these prompts through `POST /sessions/start` and check (a) Audius returns results at all, (b) the selected track's `genre`/`vibe` plausibly matches, (c) the debug panel's `pipeline_trace.candidate_retriever` shows `multi_query` served it, not the catalog fallback:

- "chill lofi beats for late night coding" (the one that returned zero hits today)
- "gym energy, high tempo"
- "arabic vocals, emotional"
- "play george wassouf" (bare artist name — also validates the LLM-artist path once Ollama has a model loaded)
- "something for deep focus, no vocals"
- a deliberately vague one: "surprise me" (should degrade gracefully to the catalog fallback via the "report plainly" contract, not crash)

---

## 11. What this design does *not* claim to fix

- Audius track metadata is sparse — `genre` and `mood` are frequently `None` on real search results (`audius_retriever.py:47-48` already codes for that possibility). `genre_score`/`mood_score` in the ranker will legitimately be `0` for a lot of real candidates; `retrieval_score` (RRF) carries more of the weight in practice than the formula might suggest. This is a metadata-availability limit of the data source, not a bug in the ranking logic.
- `_genre_energy_match` (referenced in 5.4) is a small hardcoded lookup (e.g. `techno/house/hip-hop -> high`, `ambient/lofi/classical -> low`) — a deterministic heuristic table in the same spirit as `ALLOWED_GENRES`, not a measured value. It's better than nothing but it's an approximation, and it should be named as one in code comments so a future reader doesn't mistake it for real per-track energy data.
- This does not add semantic ("feels like") matching. "Music for a breakup" won't map to anything unless the deterministic/LLM classifier maps it to a genre/mood the whitelist already understands. That's the gap the deferred embedding-based design (section 2) would close later, if it turns out to matter after the graded rubric items are done.
