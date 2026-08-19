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
catalog-only (prompts chosen to match one of the 4 seed mood buckets) so
this main batch stays deterministic and offline -- correction to an
earlier version of this docstring: this environment does, verified
directly, have real network access to Audius (both search and stream
fetch succeed); catalog-only was never a hard constraint, just the right
thing to measure first, since audio_renderer.py's real file I/O (not
network fetch latency) is what Phase 9's live-crossfade body/tail/bridge
rendering actually added. See run_audius_cache_batch() further down for
the real-network-traffic measurement (Prompt 6, opt-in via
MEASURE_AUDIUS_CACHE=1) this turned out to make possible after all.

Run directly for a human-readable report:

    cd backend && python -m scripts.measure_session_latency
"""

import json
import logging
import os
import tempfile
import time as time_module
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite://")
os.environ.setdefault("SECRET_KEY", "eval-only-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("VIBE_LLM_PROVIDER", "none")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main  # noqa: F401 -- registers every SQLAlchemy model, same reason
# eval_preferences.py imports it before create_all.
from app.database import database as db_module
from app.database.base import Base
from app.database.models.external_track import ExternalTrack
from app.database.models.session import DJSession
from app.services import session_manager
from app.services.pipeline import external_track_cache
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


def _build_session_factory(*, rebind_analysis_worker_db: bool = False) -> sessionmaker:
    """The plain catalog-only batch above never involves a second thread
    (create_session/advance_session/prepare_next never dispatch a real
    background job), so a bare in-memory engine has always been enough
    for it -- SQLAlchemy's SingletonThreadPool default gives that one
    thread a consistent connection across the whole run.

    `rebind_analysis_worker_db=True` (run_audius_cache_batch's own case)
    is different: a real background worker thread (upload_queue's pool)
    now needs to see, and write to, the exact same database this script's
    own thread is using. A shared in-memory DB was tried first via
    StaticPool (one physical connection shared by every thread) and
    rejected after hitting a real, reproducible failure: two threads each
    holding their own SQLAlchemy Session, but funneling through that one
    literal SQLite connection, corrupt each other's transaction state --
    observed directly as "OperationalError: no such savepoint:
    sa_savepoint_1" from known_broken_tracks.mark_broken's begin_nested()
    losing track of its own savepoint mid-flight because a concurrent
    commit from the *other* thread landed on the same connection first.
    SQLite's connection-scoped savepoints were never designed for two
    independent transactions to interleave on one connection -- this is a
    real limitation of this measurement harness's SQLite backend, not a
    finding about the feature under test (production runs Postgres, where
    each session already gets its own real pooled connection).

    The fix: a real temp-file SQLite database (not :memory:) with normal
    per-checkout connection pooling (no StaticPool). Every thread gets its
    own genuine connection, exactly like production's Postgres pool, and
    SQLite's own file-level locking (not a shared Python-level connection
    object) is what serializes concurrent writers -- the same isolation
    model production actually relies on, just backed by SQLite's file
    locks instead of Postgres' MVCC."""

    if rebind_analysis_worker_db:
        db_path = Path(tempfile.mkstemp(suffix=".sqlite3")[1])
        engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    else:
        engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    if rebind_analysis_worker_db:
        db_module.SessionLocal = factory
    return factory


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


# --- Persistent Audius analysis cache measurement (Prompt 6) ---------------
#
# Unlike the catalog-only batch above (deliberately offline, per its own
# docstring -- that constraint turned out to be specific to pydub/ffmpeg
# decode, not this environment's network access at all: verified directly,
# both a real Audius search and a real stream fetch succeed here, and
# librosa.load can decode the resulting mp3 via its soundfile/audioread
# backends with no ffmpeg on PATH -- only pydub's AudioSegment.from_file
# path needs ffmpeg, which is analyze_audio()'s problem, not this one).
# This section makes REAL Audius network calls -- named-artist prompts,
# chosen so catalog_retriever.is_strong_catalog_match reliably falls
# through to Audius (the local seed catalog only has 4 mood-bucket tracks
# with no named artists at all).
AUDIUS_CACHE_PROMPTS = [
    # Specific song titles, not bare artist names: a first pass using
    # broad artist-only prompts ("play daft punk") found real Audius
    # search/ranking is NOT stable call-to-call for a query that broad --
    # 0/3 repeated prompts picked the same top track twice, an itself
    # interesting, real finding (see this measurement's own report), but
    # one that made THIS specific "does a repeat encounter reuse the
    # cache" measurement meaningless without narrowing the query enough
    # that the same track reliably ranks first both times.
    "play get lucky by daft punk",
    "play instant crush by daft punk",
    "play one more time by daft punk",
]

# How long to wait for a background analyze_external_track() job to reach a
# terminal state before giving up and reporting "still pending" -- real
# analysis (a real download + real librosa DSP work) is slower than a test
# fixture's instant fake, but must still finish well within an ordinary
# human patience window for this measurement to be useful.
_ANALYSIS_WAIT_TIMEOUT_SECONDS = 30.0
_ANALYSIS_POLL_INTERVAL_SECONDS = 0.5


def _wait_for_analysis(db, external_track_id: int) -> tuple[str, float]:
    """Polls external_tracks.analysis_status until it leaves "pending" or
    _ANALYSIS_WAIT_TIMEOUT_SECONDS elapses. Returns (final_status,
    elapsed_seconds) -- elapsed_seconds is this measurement's own answer to
    Prompt 6 step 3's "confirm empirically that background analysis jobs
    actually complete," not a value any production code path depends on."""

    deadline = time_module.monotonic() + _ANALYSIS_WAIT_TIMEOUT_SECONDS
    started = time_module.monotonic()
    while time_module.monotonic() < deadline:
        db.expire_all()
        row = db.query(ExternalTrack).filter_by(id=external_track_id).first()
        if row is not None and row.analysis_status != "pending":
            return row.analysis_status, round(time_module.monotonic() - started, 2)
        time_module.sleep(_ANALYSIS_POLL_INTERVAL_SECONDS)
    return "pending", round(time_module.monotonic() - started, 2)


def _run_audius_cache_prompt(db, prompt: str) -> dict:
    """One prompt, run twice: the first create_session() is this prompt's
    guaranteed-first encounter within this fresh in-memory database (a
    brand-new external_tracks row, background analysis dispatched); after
    waiting for that analysis to finish, a second create_session() with the
    identical prompt is the "previously-cached" encounter -- same track,
    now analyzed."""

    kwargs = dict(
        retriever=get_session_candidate_retriever(),
        fallback_retriever=get_audius_candidate_retriever(),
        selector=get_segment_selector(),
        planner=get_transition_planner(),
        renderer=get_audio_renderer(),
    )

    first = session_manager.create_session(db, prompt, user_id=None, vibe=get_vibe_understander(), **kwargs)
    first_row = db.query(DJSession).filter_by(id=first.id).one()
    first_timing = dict(first_row.pipeline_trace_json.get("_timing", {}))
    first_selector = dict(first_row.pipeline_trace_json.get("segment_selector", {}))
    # tier, not the coarser fell_back -- "last_resort" is also catalog-
    # sourced (orchestrator.LAST_RESORT_CATALOG_RETRIEVER) and would
    # otherwise be miscounted as "served from Audius" here.
    served_from_audius = first_row.pipeline_trace_json["candidate_retriever"]["tier"] == "fallback"

    selected = first_row.pipeline_trace_json["candidate_retriever"]["selected_track"]
    external_row = None
    if selected["source"] == "audius":
        external_row = (
            db.query(ExternalTrack)
            .filter_by(source="audius", external_id=selected["source_track_id"])
            .first()
        )

    analysis_result = {"status": "not_applicable", "wait_seconds": 0.0}
    if external_row is not None:
        status, waited = _wait_for_analysis(db, external_row.id)
        analysis_result = {"status": status, "wait_seconds": waited}

    second = session_manager.create_session(db, prompt, user_id=None, vibe=get_vibe_understander(), **kwargs)
    second_row = db.query(DJSession).filter_by(id=second.id).one()
    second_timing = dict(second_row.pipeline_trace_json.get("_timing", {}))
    second_selector = dict(second_row.pipeline_trace_json.get("segment_selector", {}))
    second_selected = second_row.pipeline_trace_json["candidate_retriever"]["selected_track"]

    # The same free-text prompt does NOT guarantee the same *track* twice --
    # MultiQueryAudiusRetriever re-ranks a freshly re-fetched pool each
    # call (session_candidate_pool's cache is keyed by session_id, a new
    # random one per create_session), and real Audius search results can
    # reorder between calls. "Reused" must mean *this exact track* came
    # back with real data, not merely "whichever track played second time
    # happened to have data" -- checked explicitly here rather than assumed.
    same_track_replayed = (
        selected["source"] == "audius"
        and second_selected["source"] == "audius"
        and selected["source_track_id"] == second_selected["source_track_id"]
    )

    return {
        "prompt": prompt,
        "served_from_audius": served_from_audius,
        "first_encounter": {"_timing": first_timing, "segment_selector": first_selector, "selected_track": selected},
        "background_analysis": analysis_result,
        "second_encounter": {
            "_timing": second_timing, "segment_selector": second_selector, "selected_track": second_selected,
        },
        "same_track_replayed": same_track_replayed,
        "reused_completed_analysis": (
            same_track_replayed
            and second_selector.get("method") not in (None, "whole_clip")
            and second_selector.get("bpm") is not None
        ),
    }


def run_audius_cache_batch() -> list[dict]:
    # enrich_and_dispatch batches the lookup/dispatch over the WHOLE ranked
    # candidate pool (up to _CANDIDATE_LIMIT, currently 15), not just the
    # one track a session actually plays -- so one prompt's real Audius
    # search can dispatch well over a dozen background analysis jobs, most
    # of them for candidates this measurement never looks at again.
    # db_module.SessionLocal is deliberately left pointed at this batch's
    # own StaticPool engine even after this function returns (no revert):
    # this script is a one-shot process that exits right after printing
    # its report, and reverting early -- before every fire-and-forget job
    # dispatched above has actually finished on a worker thread -- would
    # otherwise point a still-in-flight job's own db_module.SessionLocal()
    # call at a DIFFERENT, un-migrated in-memory database (observed for
    # real: "no such table: external_tracks" from a job that outlived an
    # earlier version of this function's own revert-in-finally).
    external_track_cache.AUDIUS_ANALYSIS_CACHE_ENABLED = True
    session_factory = _build_session_factory(rebind_analysis_worker_db=True)
    results = []
    with session_factory() as db:
        for prompt in AUDIUS_CACHE_PROMPTS:
            try:
                results.append(_run_audius_cache_prompt(db, prompt))
            except Exception as exc:
                # A real, honest failure for one prompt (e.g. Audius
                # genuinely has no match for this specific query right
                # now) must not lose the other prompts' real results --
                # recorded plainly, not silently dropped.
                db.rollback()
                results.append({"prompt": prompt, "error": f"{type(exc).__name__}: {exc}"})
    return results


def _print_audius_cache_report(results: list[dict]) -> None:
    print(f"\n=== Persistent Audius analysis cache measurement: {len(results)} prompts ===\n")
    errored = [r for r in results if "error" in r]
    for r in errored:
        print(f"  FAILED: {r['prompt']!r} -- {r['error']}")
    reached_audius = [r for r in results if r.get("served_from_audius")]
    print(f"Resolved via Audius (not the local catalog): {len(reached_audius)}/{len(results)}")
    if not reached_audius:
        print("  (none -- AUDIUS_CACHE_PROMPTS may need adjusting; nothing else below is meaningful)")
        return

    first_retrieval_ms = [
        r["first_encounter"]["_timing"].get("retrieval_ms") for r in reached_audius
        if r["first_encounter"]["_timing"]
    ]
    print("\nFirst encounter (brand-new track) retrieval_ms:", _summarize([v for v in first_retrieval_ms if v is not None]))
    print(
        "  -- this includes enrich_and_dispatch's own cost (batched lookup + "
        "atomic insert + fire-and-forget queue submit), not just retrieval itself."
    )

    completed = [r for r in reached_audius if r["background_analysis"]["status"] == "completed"]
    print(f"\nBackground analysis completed within {_ANALYSIS_WAIT_TIMEOUT_SECONDS}s: {len(completed)}/{len(reached_audius)}")
    if completed:
        wait_seconds = [r["background_analysis"]["wait_seconds"] for r in completed]
        print("  wait_seconds:", _summarize(wait_seconds))

    same_track = [r for r in reached_audius if r["same_track_replayed"]]
    print(
        f"\nSecond create_session() picked the SAME track as the first "
        f"(not guaranteed -- real re-ranking each call): {len(same_track)}/{len(reached_audius)}"
    )
    reused = [r for r in reached_audius if r["reused_completed_analysis"]]
    print(
        f"Of those, second encounter actually reused the completed analysis "
        f"(real bpm/method, not whole-clip): {len(reused)}/{len(same_track) if same_track else 0}"
    )

    second_retrieval_ms = [
        r["second_encounter"]["_timing"].get("retrieval_ms") for r in reached_audius
        if r["second_encounter"]["_timing"]
    ]
    print("\nSecond encounter (cached track) retrieval_ms:", _summarize([v for v in second_retrieval_ms if v is not None]))

    print("\n=== Raw per-prompt results ===")
    print(json.dumps(results, indent=2, default=str))


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

    # Opt-in: makes real network calls to Audius (see
    # run_audius_cache_batch's own docstring) -- kept out of the default
    # run so this script still works as a fast, fully-offline sanity check
    # by default, same as it always has.
    if os.getenv("MEASURE_AUDIUS_CACHE") == "1":
        _print_audius_cache_report(run_audius_cache_batch())


if __name__ == "__main__":
    main()
