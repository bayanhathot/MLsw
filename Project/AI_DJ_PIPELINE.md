# The AI-DJ pipeline

This replaces the old dual-engine setup (a hardcoded 4-track dict for
sessions, a separate Audius-only path for mixes) and the unused offline
ranking baseline (`ml_pipeline.py` + DVC + MLflow, deleted). One pipeline now
serves both `POST /sessions/start` / `POST /sessions/{id}/feedback` and
`POST /mixes/start`:

```
prompt
  |
  v
VibeUnderstander        deterministic keyword parse + optional Ollama refine
  |  (PromptIntent: mood, energy, vocals, genres, artist, search_query)
  v
CandidateRetriever      catalog (Postgres, fuzzy artist match) or Audius
  |  (Track candidates, deterministic order)
  v
SegmentSelector         librosa self-similarity chorus/hook, or whole clip
  |  (SelectedSegment: start/end seconds, bpm, key, method)
  v
TransitionPlanner       deterministic BPM/key crossfade arithmetic
  |  (TransitionPlan: crossfade_ms, style, notes)
  v
AudioRenderer           pydub/ffmpeg: trims and, for 2+ tracks, crossfades
  |  (RenderedAudio: one playable file + per-segment offsets)
  v
persisted SessionState / Mix + MixSegment rows
```

All five stages live in `backend/app/services/pipeline/`.

## Why each stage is a swappable interface

`interfaces.py` defines one abstract base class per stage, each with a single
method (`VibeUnderstander.understand`, `CandidateRetriever.retrieve`,
`SegmentSelector.select`, `TransitionPlanner.plan`, `AudioRenderer.render`).
`dependencies.py` binds each interface to a concrete implementation via a
plain function, and routers/services receive the instance through FastAPI's
`Depends()`:

```python
# routers/sessions.py
retriever: CandidateRetriever = Depends(get_session_candidate_retriever)
```

Nothing downstream — `session_manager.py`, `mix_service.py`, the routers —
imports a concrete implementation directly; they only see the ABC. That's the
whole point: **swapping an implementation is a one-line change to a provider
function in `dependencies.py`**, not a change anywhere else. `get_vibe_understander`
is the one provider whose implementation is chosen by an environment
variable (`VIBE_LLM_PROVIDER`, see below) rather than a hardcoded return
value, so it can be repointed at deploy time with no code change at all — the
same one-provider-function pattern, just resolved at process startup instead
of at commit time. For the retrievers, `get_session_candidate_retriever`
currently returns the catalog retriever and `get_mix_candidate_retriever`
returns the Audius one (matching each surface's
pre-existing behavior) — repointing either is one line, independent of the
other.

### Adding a new implementation

1. Implement the relevant ABC in a new module under `pipeline/` (e.g. a
   `SpotifyCandidateRetriever(CandidateRetriever)` with a `.name` and a
   `.retrieve(db, intent, *, limit)` that returns the same `Track` shape
   `catalog_retriever.py`/`audius_retriever.py` already return).
2. Instantiate it once in `dependencies.py` and either point an existing
   provider function at it or add a new one.
3. If it's a new `CandidateRetriever`, register it in `CANDIDATE_RETRIEVERS`
   (keyed by `.name`) so a session that picked it can be looked back up by
   name on the next feedback call (`DJSession.retriever_name`).

No router, service, or schema changes are needed beyond that — the interface
contract (`Track`, `SelectedSegment`, `TransitionPlan`, `RenderedAudio` in
`app/schemas.py`) is what every stage actually depends on.

## What's deterministic, and what's the one LLM call

Deterministic, everywhere, with no exceptions:

- **Candidate ordering.** `CatalogTrackRetriever` matches a named artist via
  Postgres `pg_trgm` `similarity()` (a pure string-overlap function, not a
  learned model) with a pure-Python trigram-Jaccard fallback on any other SQL
  dialect (notably the test suite's SQLite engine) — see
  `_trigram_similarity` in `catalog_retriever.py`. With no artist named, it
  uses the same energy/vocals/mood-bucket keyword rules the old
  `session_manager._initial_track` used, now run against real rows instead of
  a dict. `AudiusCandidateRetriever` just forwards the query text to Audius's
  own search. Below `ARTIST_MATCH_THRESHOLD` (default `0.3`), the catalog
  retriever returns nothing rather than guessing.
- **Audius-to-catalog fallback.** The local catalog is a small seed/upload
  set, not a real music library -- most requests never name an artist at
  all, and even a named one is often genuinely absent from it, which is
  expected, not an error condition. Both sessions and mixes are two-tier and
  share the same priority: Audius first, and only fall through to the local
  catalog when Audius plainly finds nothing. Sessions go through
  `orchestrator.retrieve_candidates_with_fallback`
  (`session_manager._resolve_and_render`); mixes have their own equivalent,
  `mix_service._retrieve_with_fallback` (pre-existing, unaffected by this).
  A session only reports `422` when *neither* retriever finds anything —
  never a silent substitute, and never a fabricated local match. Which
  retriever actually served is recorded on `DJSession.retriever_name` per
  resolution (it can change between "audius" and "catalog" from one
  resolution to the next -- see below), and in the debug panel's
  `candidate_retriever.fell_back` trace field.
- **Segment selection.** `LibrosaSegmentSelector` reads a cached
  BPM/key/segment analysis (see below) or, for anything without one — an
  Audius preview, or a catalog upload still mid-analysis — uses the whole
  clip. No inference happens on the request path.
- **Transition planning.** `DeterministicTransitionPlanner` is arithmetic
  over known numbers: a BPM difference and a pitch-class distance produce a
  crossfade length via fixed thresholds and bonuses (see
  `transition_planner.py`'s constants). A "smoother" coaching command adds a
  fixed bonus. No weights, no training.
- **Real-time coaching** ("more energy" / "less vocals" / "smoother") mutates
  the session's stored `PromptIntent` with the same blunt, deterministic
  jumps the old code used (e.g. "more energy" always sets `energy="high"`),
  then re-runs the two-tier Audius-then-catalog resolution described above
  fresh every time — not pinned to whichever retriever served initially, so
  it recovers automatically if Audius was briefly down at session start but
  is back by the time feedback runs (or vice versa). Since feedback never
  changes `intent.artist`/`search_query`, whatever Audius found or didn't
  find initially still holds on every subsequent feedback call the same way
  it did initially.
- **Continuous advancing.** A session keeps playing without further input:
  when the current track/segment finishes, the frontend calls
  `POST /sessions/{id}/advance` automatically (`sessionStore.mediaEnded` ->
  `sessionStore.advance`, `session_manager.advance_session`), which re-runs
  the same Audius-then-catalog resolution against the session's *current,
  unmutated* intent, skipping whichever tracks the session already played
  recently (`DJSession.played_track_keys_json`, capped at the last 10) so it
  rotates through the candidate pool instead of repeating the same top
  match. Once every recent candidate has had a turn, it loops rather than
  erroring — that's the point of "continuous" for a small candidate pool.
  Explicit coaching feedback still redirects the session immediately if it
  arrives mid-loop: both endpoints just commit to the same `DJSession` row,
  so whichever request's commit lands last wins, no special locking needed.
  `advance` never mutates intent itself and is a no-op (200, session
  unchanged) if nothing currently matches -- e.g. Audius momentarily
  unreachable -- rather than ending the session outright.
- **Learned preferences.** `UserPreference` rows still record which coaching
  command a user favors, but they now bias the *next session's initial
  intent* (e.g. nudging `energy` toward `"high"`) instead of pointing at a
  literal track key — so they apply no matter which retriever ends up
  serving that session.

The **one** non-deterministic call: `VibeUnderstander` may ask an LLM to
refine `mood`/`energy`/`vocals`/`genres`/`artist`. Which LLM (if any) is a
runtime setting, **`VIBE_LLM_PROVIDER`**, resolved once at process startup in
`pipeline/dependencies.py`, not compiled into the code:

| `VIBE_LLM_PROVIDER` | Implementation | Calls | Requires |
| --- | --- | --- | --- |
| `ollama` (default) | `OllamaVibeUnderstander` | `prompt_parser.parse_prompt` | `OLLAMA_BASE_URL` + `OLLAMA_MODEL` |
| `none` | `DeterministicOnlyVibeUnderstander` | nothing — calls `deterministic_parse` directly | — |

Ollama is the sole LLM option: it's fully local, so there's no hosted-API key
to provision and no prompt text ever leaves the deployment. Turning the LLM
step off entirely (`none`) is one environment variable — no code change, no
redeploy of a different image.

### Running with Ollama

An `ollama` service (image `ollama/ollama:0.11.4`, a named volume at
`/root/.ollama` so pulled models survive redeploys, no published port —
only `backend` reaches it, over the internal Compose network) is defined in
both `docker-compose.yml` (dev) and `docker-compose.prod.yml` (prod), and
starts automatically with a plain `docker compose up` in both -- no profile
flag needed. In both files `backend`'s `depends_on` deliberately does **not**
wait on ollama's healthcheck: `VIBE_LLM_PROVIDER=ollama` is the default, but
the LLM step stays optional at every call site (`prompt_parser.parse_prompt`
fails open to the deterministic parse), so booting the API must never block
on the model container being healthy. The `ollama` container running by
itself does not change behavior — that's still `VIBE_LLM_PROVIDER` — it just
means the `ollama` option is already up and usable once a model is pulled.

To use it:

1. Pull the model once (not part of the CI/CD pipeline — a manual,
   one-time step per environment, same as any other model artifact):
   ```powershell
   docker compose exec ollama ollama pull qwen3:8b
   ```
2. Leave `VIBE_LLM_PROVIDER` unset or set it to `ollama`
   (`OLLAMA_BASE_URL`/`OLLAMA_MODEL` already default to
   `http://ollama:11434` / `qwen3:8b` in both compose files, so no further
   configuration is needed unless a different host or model is wanted). To
   turn the LLM step off instead, set `VIBE_LLM_PROVIDER=none`.
3. Restart the `backend` service.

`OllamaVibeUnderstander.understand` calls `prompt_parser.parse_prompt`, which
`POST`s to `{OLLAMA_BASE_URL}/api/generate` with `model: "qwen3:8b"`,
`format: PromptIntent.model_json_schema()`, and `stream: false` — a JSON
schema (not just an instruction) constrains Ollama's decoding, so a response
that doesn't validate against `PromptIntent` simply can't come back.

A guardrail helper (`prompt_parser._apply_guardrails`) runs on every
successful response before it's used: combined with the schema constraint and
the existing `pydantic.ValidationError` catch, any malformed output falls
back to the deterministic parse. Even on a valid response, the deterministic
pass still wins on `search_query` (always the raw prompt text) and `artist`
(the LLM's guess is only used if the deterministic regex found nothing), and
`genres` is filtered to a fixed allowlist — the LLM can't classify intent
beyond that, and can't inject an invented catalog entry into what gets
searched for. If Ollama isn't reachable, times out, returns something that
fails validation, or its concurrency limit is full, `parse_prompt`
transparently returns the deterministic result; nothing else in the pipeline
changes. A missing/incomplete `OLLAMA_BASE_URL`/`OLLAMA_MODEL` at startup logs
one warning (`pipeline/dependencies.py`) rather than crashing the app —
mirroring how `app.core.security` requires `SECRET_KEY`, but choosing to warn
instead of raising, since this is an optional refinement step, not a
correctness requirement.

## How the two old engines became one interface

- The old hardcoded 4-track `TRACKS` dict (session-only) is now
  `CatalogTrackRetriever`, reading a real `catalog_tracks` Postgres table.
  The 4 legacy rows are seeded by an Alembic migration data insert (and
  self-healed by the retriever if a database's schema was created straight
  from SQLAlchemy metadata rather than migrations, as the test suite's
  SQLite engine does) — same descriptive copy ("Gym energy", "Emotional
  vocals", "Deep work focus", "Smooth flow"), same demo audio asset. This is
  also the table `POST /catalog/tracks` (see below) writes into, which is
  what makes the fuzzy artist search resolve against a real, growing catalog
  instead of a fixed list.
- The old Audius-only mix path is now `AudiusCandidateRetriever`, an
  interface-conforming wrapper around the unchanged `audius_service.py`.
- Both endpoints route through the same `SegmentSelector`/
  `TransitionPlanner`/`AudioRenderer` instances — one code path, not two.
  Sessions and mixes both primary-retrieve from Audius and fall back to the
  catalog when Audius returns nothing: `orchestrator.
  retrieve_candidates_with_fallback` for sessions, and `mix_service.
  _retrieve_with_fallback` for mixes (which also drops any artist filter as
  an absolute last resort, since a mix must never hard-fail the way a
  session can plainly report "no match" — mirroring the old
  `local_demo_track()` safety net, just backed by real data instead of one
  hardcoded dict). A generic vibe/genre request with no named artist -- most
  requests -- used to hit the catalog's always-returns-something no-artist
  path and never reach Audius at all for sessions; Audius going first for
  both surfaces now is what actually makes it answer what was asked instead
  of looping the same handful of local demo tracks.

## The new upload endpoint and analysis job

`POST /catalog/tracks` (multipart form: `album`, `artist`, `lyrics` + the
audio file) is additive, not a replacement for `POST /uploads/jobs` (which
stays exactly as-is for forum/message attachments with no track metadata).
It validates the file by the same byte-signature check attachments use
(`upload_queue.validate_upload`), stores it through the *same* `UploadQueue`
worker pool (a new `storage_subdir="catalog"` keeps it out of the attachment
namespace), inserts a `catalog_tracks` row, and queues the one-time
BPM/key/best-segment analysis (`audio_analysis.py`) onto that same worker
pool via `UploadQueue.submit_analysis` — no second async system. Analysis
runs librosa: `beat_track` for BPM, a strongest-average-chroma-bin heuristic
for key, and a self-similarity matrix over ~1-second chroma buckets (bounded
regardless of track length) to find the most repeated/representative ~30s
window as the chorus/hook proxy. `SegmentSelector` just reads the result;
nothing on the request path waits for analysis to finish.

## Real rendering, not a metadata placeholder

The old mix code wrote `MixSegment` rows with `end_second=min(45, duration)`
and a `transition_to_next` label that no audio ever actually reflected.
`PydubAudioRenderer` now does the real work: for one track it trims to the
selected segment; for 2+ tracks it loads each one (a local file for catalog
tracks, a bounded download for Audius) and crossfades adjacent segments with
pydub using the planner's crossfade length, exporting one composite WAV file
(WAV export/import is pure-Python in pydub, so this core path works even
without ffmpeg installed; ffmpeg — added to `backend/Dockerfile` — is what
lets it decode compressed uploads/streams). Every `MixSegment` row for that
mix points at the same rendered file with the real cumulative offset, which
is exactly the shape the frontend already expects (it seeks within a
segment's own `audio_url` using `start_second`/`end_second`), so no frontend
change was needed. If a track's audio genuinely can't be fetched, that
segment is left as an honest, unblended pass-through instead of a fabricated
crossfade.

## Analytics: one event stream, regardless of source

`listening_service.create_event` (idempotency + timestamp/segment validation,
unchanged) is still the single write path, called by the frontend when a
segment starts playing. What changed is `_session_context`: it used to look
up `TRACKS[session.track_key]`, which no longer exists. It now reads
whatever the session's persisted `now_playing_json` currently holds — title,
artist, genre, vibe label, segment bounds — which is populated identically
whichever `CandidateRetriever` produced it. `_mix_context` was already
retriever-agnostic (it reads persisted `MixSegment` columns) and didn't need
to change. Music Identity therefore gets one consistent event stream no
matter which engine served a given track.

## Internal pipeline/Ollama debug panel

`session_manager._resolve_and_render` also builds a `pipeline_trace` dict --
which concrete implementation handled each of the four downstream stages
(candidate retriever, segment selector, transition planner, audio renderer)
plus a short result from each -- stored on `DJSession.pipeline_trace_json`
alongside `now_playing_json`/`reasoning_json`. `create_session` fills in the
`vibe_understander` stage as `invoked: true`; feedback-triggered
re-resolution fills it in as `invoked: false` (feedback mutates the stored
intent deterministically and never calls the LLM again).

`GET /debug/pipeline` (`routers/debug.py`) returns the trace for recent
sessions plus a live Ollama health probe (`pipeline/ollama_health.py`:
reachable, currently loaded model(s) via `/api/ps`) and the latency/outcome
of the last *real* `parse_prompt` call (tracked in `prompt_parser.py`, not a
synthetic ping). `WS /debug/ws` pushes an invalidation signal on every new
trace, same pattern as `/posts/ws/community`. Both are gated behind
`ENABLE_PIPELINE_DEBUG` (off by default) and a logged-in user -- see
`ZONIX_PROJECT_README.md`'s "Internal debug panel" section. Observability
only: nothing here can trigger or change pipeline behavior.

## Deliberately left for later

- **A real trained ranking/recommendation model.** This design has no
  scoring/ranking stage anywhere — ordering is deterministic string
  similarity, keyword rules, and BPM/key arithmetic. The old
  `ml_pipeline.py` offline evaluation (DVC + MLflow, a tag-overlap baseline
  nothing in the app ever called) was deleted rather than adapted, since
  keeping a disconnected "baseline" around a redesigned deterministic
  pipeline would be actively misleading. If a trained model is wanted later
  (e.g. a learned re-ranker over `CandidateRetriever` output, or a real
  key/BPM classifier replacing the heuristics in `audio_analysis.py`), it
  plugs in as a new stage implementation the same way any other swap would —
  DVC/MLflow tooling can come back at that point, scoped to that model.
- **Listening DNA** (`UserMusicProfile.dna_*`) — unchanged from before this
  work, still deferred; see `MUSIC_IDENTITY.md`.
