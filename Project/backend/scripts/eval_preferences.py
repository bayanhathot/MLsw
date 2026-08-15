"""Offline, labeled evaluation of whether a learned UserPreference
measurably improves ranked candidate results for an otherwise-neutral
prompt.

Addresses CUEMIX_PROJECT_README.md's "Long-term memory" completion
criterion: "Verify that preferences improve ranked results with a labeled
evaluation."

What this actually exercises, end to end -- the real code, not a
reimplementation of it:

  1. A synthetic user accumulates a real, persisted UserPreference row for
     "more_energy" (the same row session_manager.apply_feedback would build
     up from repeated "More energy" clicks -- that increment arithmetic
     itself is covered separately by tests/test_sessions.py's feedback
     tests, so this harness only re-creates its *result*, not the request
     flow).
  2. session_manager._initial_intent() -- the real function every session
     creation calls -- resolves an otherwise-neutral prompt for both this
     user (preference applies) and a guest with no learned preference at
     all (the real, non-hand-constructed baseline for the same prompt).
  3. audius_retriever._rank_by_metadata() -- the real ranking function --
     ranks one synthetic, labeled candidate pool (half tagged "energy",
     half "chill", shuffled) against both intents.

Metric: precision@K -- the fraction of the top K ranked candidates that are
"high energy" tracks. Run directly for a human-readable report:

    cd backend && python -m scripts.eval_preferences

Or imported by tests/test_preference_eval.py, which asserts a concrete
improvement threshold on a fixed seed (regression coverage, not just a
one-off report).
"""

import os
import random

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite://")
os.environ.setdefault("SECRET_KEY", "eval-only-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("VIBE_LLM_PROVIDER", "none")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.main  # noqa: F401 -- importing the app registers every SQLAlchemy
# model on Base.metadata (User.mixes and friends resolve their string-based
# relationships), the same reason conftest.py imports it before create_all.
from app.database.base import Base
from app.database.models.session import UserPreference
from app.database.models.user import User
from app.schemas import PromptIntent, Track
from app.services import session_manager
from app.services.pipeline.audius_retriever import _rank_by_metadata
from app.services.pipeline.vibe import DeterministicOnlyVibeUnderstander

NEUTRAL_PROMPT = "play some music"
TOP_K = 5
POOL_SIZE = 20
DEFAULT_SEED = 1234


def _build_session_factory() -> sessionmaker:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, email=f"{username}@eval.invalid", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _give_energy_preference(db: Session, user_id: int, *, times: int) -> None:
    """Builds the exact UserPreference row `times` repeated "More energy"
    clicks would leave behind (see session_manager.apply_feedback's
    preference_key == "more_energy" branch)."""

    preference = UserPreference(user_id=user_id, feedback="more_energy", score=0, count=0)
    preference.count += times
    preference.score += times
    db.add(preference)
    db.commit()


def _synthetic_pool(seed: int, size: int = POOL_SIZE) -> tuple[dict[str, Track], list[str]]:
    """`size` candidates, half labeled "energy" and half "chill" purely via
    their own `tags` field -- the only thing distinguishing them, so
    nothing here is circular with how ranking decides a winner. Shuffled
    with `seed` so the unbiased ranking isn't trivially already sorted by
    label; returns (pool, fused_order) shaped exactly like
    MultiQueryAudiusRetriever.retrieve()'s own RRF-fused pool going into
    _rank_by_metadata."""

    tracks = []
    for index in range(size):
        label = "energy" if index % 2 == 0 else "chill"
        tracks.append(
            Track(
                source="audius",
                source_track_id=f"eval-{index}",
                title=f"Eval Track {index}",
                artist=f"Artist {index}",
                album=None,
                audio_url=f"https://audio.example/eval-{index}",
                cover_url=None,
                duration_seconds=180,
                genre=None,
                vibe=None,
                vibe_label=None,
                tags=label,
                catalog_track_id=None,
                local_path=None,
            )
        )
    random.Random(seed).shuffle(tracks)
    pool = {f"{track.source}:{track.source_track_id}": track for track in tracks}
    return pool, list(pool.keys())


def _precision_at_k(
    pool: dict[str, Track], fused_order: list[str], intent: PromptIntent, *, k: int = TOP_K
) -> float:
    ranked, _breakdown = _rank_by_metadata(pool, fused_order, intent, recent_artists=frozenset())
    top = ranked[:k]
    hits = sum(1 for key in top if pool[key].tags == "energy")
    return hits / len(top)


def run_eval(seed: int = DEFAULT_SEED, *, preference_uses: int = 5) -> dict:
    """Returns the full comparison as a plain dict so both main() (a human
    report) and tests/test_preference_eval.py (a fixed-seed assertion) share
    one real implementation instead of two that could quietly drift apart."""

    session_factory = _build_session_factory()
    with session_factory() as db:
        user = _make_user(db, f"eval_energy_lover_{seed}")
        _give_energy_preference(db, user.id, times=preference_uses)

        vibe = DeterministicOnlyVibeUnderstander()
        biased_intent, _raw = session_manager._initial_intent(NEUTRAL_PROMPT, db, user.id, vibe)
        # The real, non-hand-constructed baseline: the same neutral prompt,
        # resolved for a guest with no learned preference at all.
        baseline_intent, _raw = session_manager._initial_intent(NEUTRAL_PROMPT, db, None, vibe)

    pool, fused_order = _synthetic_pool(seed)
    baseline_precision = _precision_at_k(pool, fused_order, baseline_intent)
    biased_precision = _precision_at_k(pool, fused_order, biased_intent)

    return {
        "baseline_intent_energy": baseline_intent.energy,
        "biased_intent_energy": biased_intent.energy,
        "baseline_precision_at_k": baseline_precision,
        "biased_precision_at_k": biased_precision,
        "improvement": biased_precision - baseline_precision,
    }


def main() -> None:
    result = run_eval()
    print(f"Neutral prompt: {NEUTRAL_PROMPT!r}")
    print(f"Baseline intent energy (no learned preference): {result['baseline_intent_energy']}")
    print(f"Biased intent energy (learned more_energy preference): {result['biased_intent_energy']}")
    print(f"precision@{TOP_K} baseline: {result['baseline_precision_at_k']:.2f}")
    print(f"precision@{TOP_K} biased:   {result['biased_precision_at_k']:.2f}")
    print(f"Improvement: {result['improvement']:+.2f}")


if __name__ == "__main__":
    main()
