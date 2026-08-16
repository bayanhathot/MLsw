"""Cold-seed environment configuration -- see app/seed.py's module docstring
for how these are wired into the deploy chain."""

import os

DEFAULT_VERSION = "v1"
DEFAULT_RANDOM_SEED = 2026


def enabled() -> bool:
    return os.getenv("ENABLE_COLD_SEED", "true").strip().lower() in {"1", "true", "yes"}


def version() -> str:
    return os.getenv("COLD_SEED_VERSION", DEFAULT_VERSION).strip() or DEFAULT_VERSION


def random_seed() -> int:
    raw = os.getenv("COLD_SEED_RANDOM_SEED", "").strip()
    if not raw:
        return DEFAULT_RANDOM_SEED
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_RANDOM_SEED
