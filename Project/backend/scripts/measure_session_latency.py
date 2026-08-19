"""§8 observability batch measurement: does 12-15's per-stage latency
instrumentation show anything surprising, and does prepare_next() actually
finish with margin before the frontend's own deadline?

Measurement only -- this script reports findings, it does not fix anything
it finds (see the module docstring in session_manager.py's _log_stage_latency
and this repo's own "flag it as a follow-up" convention).

Reuses Phase 2 Prompt 11's batch approach (run N representative prompts
through the *real* pipeline and inspect pipeline_trace_json) -- that script
itself is no longer in-tree (not committed at the time), so this is a fresh
implementation of the same idea, now specifically instrumented for latency
rather than retrieval-source split. Uses the real production dependency
wiring (app.services.pipeline.dependencies), the real seeded demo catalog
(self-healing, see catalog_retriever._ensure_seed_catalog), and real pydub
rendering against the bundled demo WAV -- not mocks. Deliberately stays
catalog-only (prompts chosen to match one of the 4 seed mood buckets):
this sandboxed environment has no real network access to Audius, and
catalog-only measurement is still the right thing to look at first since
audio_renderer.py's real file I/O (not network fetch latency) is what
Phase 9's live-crossfade body/tail/bridge rendering actually added.

Run directly for a human-readable report:

    cd backend && python -m scripts.measure_session_latency
"""

import json
import logging
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite://")
os.environ.setdefault("SECRET_KEY", "eval-only-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("VIBE_LLM_PROVIDER", "none")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main  # noqa: F401 -- registers every SQLAlchemy model, same reason
# eval_preferences.py imports it before create_all.
from app.database.base import Base
from app.database.models.session import DJSession
from app.services import session_manager
from app.services.pipeline.dependencies import (
    get_audio_renderer,
    get_audius_candidate_retriever,
    get_segment_selector,
    get_session_candidate_retriever,
    get_transition_planner,
    get_vibe_understander,
)

logging.basicConfig(level=logging.INFO)

# Each maps cleanly onto one of catalog_retriever._SEED_TRACKS' own
# mood_bucket values, so every session in this batch resolves via the
# local catalog alone -- no Audius network call, deterministic, and
# exercises the real audio_renderer.py file I/O this measurement actually
# cares about.
PROMPTS = [
    "energetic workout music to get me pumped",
    "high energy gym session tracks",
    "need something intense for a hard workout",
    "smooth chill background music",
    "relaxed smooth vibes for the evening",
    "easy smooth flow, nothing too intense",
    "deep focus music for studying",
    "focus tracks for concentrating on work",
    "instrumental focus music, no distractions",
    "emotional vocal heavy song",
    "vocal-driven track with real feeling",
    "something with powerful vocals",
]


def _build_session_factory() -> sessionmaker:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _run_one_session(db, prompt: str) -> dict:
    """Runs create_session -> advance (fast-path, then a real
    fresh-resolution advance) -> prepare_next against the real pipeline,
    returning every _timing dict actually produced plus prepare_next's own
    independently-measured wall-clock margin."""

    kwargs = dict(
        retriever=get_session_candidate_retriever(),
        fallback_retriever=get_audius_candidate_retriever(),
        selector=get_segment_selector(),
        planner=get_transition_planner(),
        renderer=get_audio_renderer(),
    )

    session_read = session_manager.create_session(
        db, prompt, user_id=None, vibe=get_vibe_understander(), **kwargs
    )
    row = db.query(DJSession).filter_by(id=session_read.id).one()
    create_timing = dict(row.pipeline_trace_json.get("_timing", {}))

    # First advance(): with a real seeded 45s segment and the default
    # RESERVED_TRANSITION_MS, this almost always takes the reserved_plain
    # fast path (no fresh resolution) -- exactly what advance_session's own
    # resolved=False log line is for. The *second* advance() is what
    # actually triggers a fresh resolution worth timing.
    session_manager.advance_session(db, row, **kwargs)
    db.refresh(row)
    session_manager.advance_session(db, row, **kwargs)
    db.refresh(row)
    advance_timing = dict(row.pipeline_trace_json.get("_timing", {}))

    # prepare_next() only does real work while stage == "body" -- true
    # again after the second advance() above landed on a fresh body.
    import time as time_module

    prepare_started = time_module.perf_counter()
    session_manager.prepare_next(db, row, **kwargs)
    prepare_duration_ms = round((time_module.perf_counter() - prepare_started) * 1000, 2)
    db.refresh(row)
    prepare_resolved = row.prepared_next_json is not None
    prepare_timing = (
        dict(row.prepared_next_json["pipeline_trace"].get("_timing", {})) if prepare_resolved else {}
    )

    return {
        "prompt": prompt,
        "create": create_timing,
        "advance": advance_timing,
        "prepare_next": {
            "resolved": prepare_resolved,
            "duration_ms": prepare_duration_ms,
            **prepare_timing,
        },
    }


def run_batch() -> list[dict]:
    session_factory = _build_session_factory()
    results = []
    with session_factory() as db:
        for prompt in PROMPTS:
            results.append(_run_one_session(db, prompt))
    return results


def _summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "avg_ms": round(sum(values) / len(values), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
    }


def main() -> None:
    results = run_batch()

    print(f"\n=== §8 batch latency measurement: {len(results)} sessions ===\n")

    create_total = [r["create"]["total_ms"] for r in results if r["create"]]
    print("create_session total_ms:", _summarize(create_total))

    advance_resolved = [r["advance"] for r in results if r["advance"]]
    print(f"advance_session (2nd call) reached a fresh resolution: {len(advance_resolved)}/{len(results)}")
    if advance_resolved:
        print("  total_ms:", _summarize([a["total_ms"] for a in advance_resolved]))
        print("  audio_renderer_ms:", _summarize([a["audio_renderer_ms"] for a in advance_resolved]))

    prepare_resolved = [r["prepare_next"] for r in results if r["prepare_next"]["resolved"]]
    print(f"\nprepare_next() resolved (built a real bridge): {len(prepare_resolved)}/{len(results)}")
    if prepare_resolved:
        durations = [p["duration_ms"] for p in prepare_resolved]
        print("  duration_ms:", _summarize(durations))
        beat_min = sum(1 for d in durations if d <= session_manager._PREPARE_NEXT_MIN_FRONTEND_DEADLINE_MS)
        beat_client = sum(1 for d in durations if d <= session_manager._PREPARE_NEXT_CLIENT_TIMEOUT_MS)
        print(
            f"  finished within the {session_manager._PREPARE_NEXT_MIN_FRONTEND_DEADLINE_MS}ms "
            f"worst-case frontend deadline: {beat_min}/{len(durations)}"
        )
        print(
            f"  finished within the {session_manager._PREPARE_NEXT_CLIENT_TIMEOUT_MS}ms "
            f"client abort timeout: {beat_client}/{len(durations)}"
        )
        margins = [session_manager._PREPARE_NEXT_MIN_FRONTEND_DEADLINE_MS - d for d in durations]
        print("  margin vs the 10s worst-case deadline (ms):", _summarize(margins))

    print("\n=== Raw per-session results ===")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
