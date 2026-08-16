"""Marks that a given cold-seed dataset version has already been generated.

Idempotency for app/coldseed's large synthetic dataset works two ways: this
table is the fast path (one indexed lookup skips the whole run on every
redeploy after the first), and the seed itself only ever commits once, in a
single transaction (see coldseed/build.py), so a run that fails partway
rolls back completely rather than leaving partial, undetectable duplicates
behind for the next run to double up on.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.database.base import Base


class ColdSeedRun(Base):
    __tablename__ = "cold_seed_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
