# Cuemix backend

FastAPI + PostgreSQL service for auth, DJ sessions, the mix library, catalog
uploads, community/social features, and Music Identity analytics.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 5000
```

Requires `DATABASE_URL` and `SECRET_KEY` in the environment (see
`../.env.example`, or `DATABASE_URL_LOCAL` for a non-Docker Postgres). The
frontend dev server proxies `/api` to `127.0.0.1:5000` by default.

## Layout

- `app/routers/` — `auth`, `sessions`, `mixes`, `catalog`, `forum`, `social`,
  `profiles`, `messaging`, `uploads`, `listening`, `debug`, `media`, `realtime`.
- `app/services/` — business logic, one module per concern
  (`session_manager`, `mix_service`, `prompt_parser`, `audius_service`,
  `audio_analysis`, `upload_queue`, `music_identity_service`,
  `channel_hub`, `social_service`, `profile_service`, `auth_service`, ...).
- `app/services/pipeline/` — the AI-DJ pipeline: `interfaces.py` defines the
  five stage ABCs (`VibeUnderstander`, `CandidateRetriever`,
  `SegmentSelector`, `TransitionPlanner`, `AudioRenderer`);
  `dependencies.py` wires the concrete implementations
  (`audius_retriever.py`, `catalog_retriever.py`, `query_planner.py`,
  `segment_selector.py`, `transition_planner.py`, `audio_renderer.py`,
  `orchestrator.py`, `ollama_health.py`).
- `app/database/models/` — SQLAlchemy models, one module per domain
  (`user`, `profile`, `session`, `mix`, `mix_social`, `catalog`, `forum`,
  `social`, `messaging`, `music_identity`, `attachment`).
- `scripts/` — standalone evaluation scripts (`eval_preferences.py`,
  `eval_llm_reasoning.py`) — see [Evaluations](#evaluations) below.
- `alembic/versions/` — migrations. Any model change must land with a
  migration in the same change; `python -m alembic check` verifies there's
  no drift.
- `tests/` — pytest suite (unit + integration), run against a real Postgres.

## Session pipeline notes

`session_manager.py` caches candidate pools by a retrieval fingerprint
(`session_candidate_pool.fingerprint_for`) and can prepare the next segment
ahead of playback (`session.prepared_next_json`). A prepared result is only
reused if it was resolved against the *exact same* fingerprint as the
session's current intent; any intent mutation (new prompt, feedback, skip)
invalidates it. This exists purely to avoid a visible stall between segments
— it's not a correctness requirement, and every path that consumes a
prepared result re-validates the fingerprint first.

## Evaluations

Two evaluations verify the "Local LLM Integration" requirement's
Performance and Concurrency criteria, in addition to the normal pytest gate:

- **Concurrency** — `tests/test_external_services.py::test_concurrent_parse_prompt_calls_respect_the_ollama_slot_bound`
  runs in the standard `pytest` suite (mocked Ollama, no live model needed).
  It fires 5x `prompt_parser._ollama_slots`' configured limit at the real
  `parse_prompt()` concurrently against an artificially slow mock, and
  asserts the number of calls actually in flight against "Ollama" never
  exceeds the configured `OLLAMA_MAX_CONCURRENCY`, and that every caller
  still returns a valid `PromptIntent` (callers that miss a slot within the
  real 0.05s timeout fall back to the deterministic parse rather than
  blocking). **Last verified result (2026-08-15, commit `a3a1c63`, local
  run):** 20 concurrent callers against a limit of 4 → high-water-mark
  **4/4**, wall-clock **0.80s**, 20/20 valid `PromptIntent` results, 0
  failures.
- **Performance (math/context reasoning)** — `scripts/eval_llm_reasoning.py`
  is a standalone script, **not part of the pytest gate**, that needs a
  genuinely live, reachable Ollama with `OLLAMA_MODEL` already pulled (the
  same reason `ffmpeg`/Audius aren't fully exercised in the default
  local/CI run). It sends a scripted multi-turn `/api/chat` exchange —
  state two tracks' BPM in an early turn, unrelated filler in the middle,
  then a final question requiring both arithmetic and recalling the early
  turn's numbers — and checks the reply numerically (parsed percentage vs.
  the real value, ±1%) and for context retention (original BPM values
  present, not hallucinated ones). Run it against a live instance with:

  ```powershell
  cd backend
  python -m scripts.eval_llm_reasoning
  ```

  **Last verified result (2026-08-15, commit `74b9f06`, run live against
  `docker-compose.prod.yml`'s `ollama` service on the Azure VM,
  `qwen3:8b`):** **PASS.** Full reply:

  > Track A: 120 BPM
  > Track B: 128 BPM
  >
  > To calculate the percentage increase in tempo: (128 − 120) / 120 × 100
  > = 6.7%
  >
  > So, the tempo increases by **6.7%** when transitioning from Track A
  > (120 BPM) to Track B (128 BPM).

  Numeric check: expected 6.7%, extracted 6.7% — **PASS** (exact match,
  well within the ±1% tolerance). Context-retention check: both original
  BPM values present, not hallucinated — **PASS**. Script-measured
  round-trip latency: **22.7s** (`~45s` wall-clock including the
  `docker compose exec` invocation overhead).

  **Caveat worth flagging, not glossing over:** that 22.7s is well past
  `prompt_parser.py`'s production `OLLAMA_TIMEOUT_SECONDS` default of
  **3.0s**. This eval's 5-turn exchange is heavier than the single-shot
  classification call `parse_prompt()` actually makes, so it isn't
  proof the production path times out too — but it's close enough to
  be a real open question, not a settled one. Worth measuring the
  single-shot call's actual latency on this VM before trusting that
  Ollama refinement succeeds more often than it silently falls back to
  the deterministic parse in production.

  First run (same day, same commit's predecessor `cb55619`) failed with
  the script's own 10s default timeout before this fix
  (`scripts/eval_llm_reasoning.py` wasn't even present in the deployed
  image yet — see `74b9f06`, which added `COPY scripts ./scripts` to
  `backend/Dockerfile`, a pre-existing gap this eval surfaced).

## Tests and checks

```powershell
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
python -m alembic upgrade head
python -m alembic check
```

## Operational scripts

- `python -m app.seed` — idempotent demo-data seed, on by default
  (`ALLOW_DEMO_SEED=true`); runs automatically as part of the `migrate`
  service on every deploy (see docker-compose.yml), so the app launches
  pre-seeded. Set `ALLOW_DEMO_SEED=false` to opt out. Creates `.invalid`-domain
  demo accounts.
- `python -m app.cleanup_uploads` — dry-run by default; reports orphaned
  attachment files. Add `--delete --confirm-backend-stopped` to actually
  remove them, with the backend stopped.
- `app/static/audio/generate_demo.py` — regenerates the original,
  procedurally generated `cuemix-demo.wav` fallback track (60s mono
  22.05kHz 16-bit PCM); see
  [app/static/audio/GENERATED_AUDIO.md](app/static/audio/GENERATED_AUDIO.md)
  for the pinned hash and why it's not a third-party sample.

## Gotchas

- Set `TRUST_PROXY_HEADERS=true` only when actually running behind a
  trusted reverse proxy (e.g. the production Caddy front end) — otherwise
  client IP / scheme headers can be spoofed.
- `BACKEND_WORKERS` must stay `1`: notification fanout, the upload queue,
  and rate limiting are all process-local, not shared across replicas.
- No token revocation, refresh-token flow, or admin role exists yet — a
  known limitation, not an oversight.
