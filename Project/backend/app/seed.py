"""Cold-seed entry point: populates a fresh database with a realistic,
months-old-looking dataset (~50 accounts, profiles, a social graph, forum
activity, direct messages, mixes, DJ sessions, and listening history --
see app/coldseed/build.py for the full generator and its module docstring
for how it stays idempotent and offline).

Runs by default as part of every deploy's one-shot `migrate` step (see
docker-compose.yml/docker-compose.prod.yml), right after `alembic upgrade
head`, so the app always launches pre-seeded. Re-running it on every
redeploy is safe and never creates duplicates (app/coldseed/build.py's
ColdSeedRun version marker). Set ENABLE_COLD_SEED=false to opt out entirely;
when disabled, main() is a no-op (prints and returns) rather than failing,
since it's chained with other startup commands. COLD_SEED_VERSION and
COLD_SEED_RANDOM_SEED (see app/coldseed/config.py) control which dataset
version runs and its reproducible random seed.

Manual run::

    python -m app.seed
"""

from sqlalchemy.orm import Session

from app.coldseed import config
from app.coldseed.build import run_cold_seed
from app.database.database import SessionLocal


def seed_demo_data(db: Session) -> dict:
    """Thin, explicit-args wrapper around the real generator -- kept as the
    stable function tests call directly against a test session, independent
    of env-var reading (see main()'s own ENABLE_COLD_SEED gate)."""

    return run_cold_seed(db, version=config.version(), random_seed=config.random_seed())


def main() -> None:
    if not config.enabled():
        print("Cold seed skipped: ENABLE_COLD_SEED is explicitly disabled.")
        return
    with SessionLocal() as db:
        result = seed_demo_data(db)
    print(f"Cold seed complete: {result}")


if __name__ == "__main__":
    main()
