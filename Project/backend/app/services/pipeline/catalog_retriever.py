"""CandidateRetriever backed by the real, Postgres-resident catalog_tracks
table -- this is what the old hardcoded 4-track TRACKS dict became.

Two matching strategies:
  * intent.artist is set -> fuzzy-match it against CatalogTrack.artist using
    Postgres pg_trgm similarity() (falls back to an equivalent pure-Python
    trigram-Jaccard similarity on any other SQL dialect, notably the SQLite
    engine the test suite uses -- see _trigram_similarity). Below
    ARTIST_MATCH_THRESHOLD this returns an empty list rather than a guess --
    requirement 8's "report that plainly" behavior.
  * no artist named -> the same energy/vocals/mood-bucket keyword rules
    session_manager used to run against the TRACKS dict, now run against
    real rows tagged with `mood_bucket`.
"""

import logging
import os
import shutil
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.database.models.catalog import CatalogTrack
from app.schemas import PromptIntent, Track
from app.services import upload_queue
from app.services.pipeline.interfaces import CandidateRetriever

logger = logging.getLogger(__name__)

CATALOG_AUDIO_SUBDIR = "catalog"
ARTIST_MATCH_THRESHOLD = float(os.getenv("ARTIST_MATCH_THRESHOLD", "0.3"))

# The 4 seeded demo rows (migration data insert) point at this repo-bundled
# asset -- the same file the old TRACKS dict used for every bucket -- rather
# than something already sitting in UPLOAD_DIR. It's staged into place on
# first use instead of at migration time, since UPLOAD_DIR is an
# environment-resolved runtime path (tests monkeypatch it per-run).
_SEED_AUDIO_SOURCE = Path(__file__).resolve().parents[2] / "static" / "audio" / "zonix-demo.wav"

# Canonical content for the 4 legacy TRACKS-dict rows. The Alembic migration
# inserts these for a real `alembic upgrade head` deployment; this module
# additionally self-heals an empty table (e.g. a database whose schema was
# created straight from SQLAlchemy metadata rather than via migrations, as
# the test suite's SQLite engine does) so the catalog retriever always has
# something to match against.
_SEED_TRACKS = [
    {"title": "Momentum Loop", "artist": "Zonix AI DJ", "album": "Workout Demo Catalog", "mood_bucket": "energy", "vibe_label": "Gym energy"},
    {"title": "Midnight Whispers", "artist": "Zonix AI DJ", "album": "Vocal Demo Catalog", "mood_bucket": "vocals", "vibe_label": "Emotional vocals"},
    {"title": "Focus Loop 01", "artist": "Zonix AI DJ", "album": "Focus Demo Catalog", "mood_bucket": "focus", "vibe_label": "Deep work focus"},
    {"title": "Smooth Flow Demo", "artist": "Zonix AI DJ", "album": "General Demo Catalog", "mood_bucket": "smooth", "vibe_label": "Smooth flow"},
]


def _ensure_seed_catalog(db: Session) -> None:
    if db.query(CatalogTrack.id).first() is not None:
        return
    for seed in _SEED_TRACKS:
        db.add(
            CatalogTrack(
                **seed,
                storage_name="zonix-demo.wav",
                content_type="audio/wav",
                duration_seconds=60,
                analysis_status="completed",
                segment_start_second=0,
                segment_end_second=45,
                segment_method="whole_clip",
            )
        )
    db.commit()


def _mood_bucket_for(intent: PromptIntent) -> str:
    # intent.search_query is always the lowercased, whitespace-normalized
    # prompt text (prompt_parser.parse_prompt guarantees this even when the
    # LLM path ran), so these keyword checks work the same as the original
    # session_manager._initial_track logic did against the raw prompt.
    text = intent.search_query
    if intent.energy == "high" or any(word in text for word in ("gym", "energy", "workout")):
        return "energy"
    if intent.vocals == "more" or any(word in text for word in ("arabic", "vocal")):
        return "vocals"
    if intent.energy == "low" or any(word in text for word in ("coding", "focus", "work")):
        return "focus"
    return "smooth"


def _trigrams(value: str) -> set[str]:
    # pg_trgm pads its input with 2 leading/trailing spaces before extracting
    # trigrams; matching that here keeps short strings (e.g. "Q") from
    # producing zero trigrams and keeps scores comparable in spirit.
    padded = f"  {value.casefold()}  "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    """A pure-Python analogue of Postgres pg_trgm's similarity(): trigram-set
    Jaccard overlap. Deliberately symmetric and order-independent -- unlike
    difflib.SequenceMatcher.ratio(), which this replaced after it returned
    different scores depending on argument order (0.24 vs 0.39 for the same
    pair), silently corrupting the "below threshold" guarantee."""

    trigrams_a, trigrams_b = _trigrams(a), _trigrams(b)
    if not trigrams_a or not trigrams_b:
        return 0.0
    return len(trigrams_a & trigrams_b) / len(trigrams_a | trigrams_b)


def _fuzzy_artist_matches(db: Session, artist: str, limit: int) -> list[CatalogTrack]:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        similarity = func.similarity(CatalogTrack.artist, artist)
        return (
            db.query(CatalogTrack)
            .filter(similarity >= ARTIST_MATCH_THRESHOLD)
            .order_by(similarity.desc(), CatalogTrack.id.asc())
            .limit(limit)
            .all()
        )

    # No pg_trgm outside Postgres: an equivalent deterministic Python-side
    # similarity over the catalog. Fine at this table's scale; not a ranking
    # model (it's a single, unlearned string-similarity function).
    scored = [(row, _trigram_similarity(row.artist, artist)) for row in db.query(CatalogTrack).all()]
    scored = [item for item in scored if item[1] >= ARTIST_MATCH_THRESHOLD]
    scored.sort(key=lambda item: (-item[1], item[0].id))
    return [row for row, _ in scored[:limit]]


def _ensure_local_file(row: CatalogTrack, path: Path) -> None:
    """Stages the seeded demo asset into UPLOAD_DIR on first use. Real
    uploads are already written there by upload_queue.py, so this is a
    no-op for anything with an owner."""

    if path.exists() or row.owner_id is not None:
        return
    if not _SEED_AUDIO_SOURCE.is_file():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SEED_AUDIO_SOURCE, path)
    except OSError:
        logger.warning("Could not stage seeded catalog audio at %s", path)


def _track_local_path(row: CatalogTrack) -> Path:
    path = upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / row.storage_name
    _ensure_local_file(row, path)
    return path


def _to_track(row: CatalogTrack) -> Track:
    return Track(
        source="catalog",
        source_track_id=str(row.id),
        title=row.title,
        artist=row.artist,
        album=row.album,
        audio_url=public_api_url(f"/catalog/tracks/{row.id}/audio"),
        cover_url=None,
        duration_seconds=row.duration_seconds,
        genre=row.genre,
        vibe=row.mood_bucket,
        vibe_label=row.vibe_label,
        catalog_track_id=row.id,
        local_path=str(_track_local_path(row)),
    )


class CatalogTrackRetriever(CandidateRetriever):
    name = "catalog"

    def retrieve(
        self,
        db: Session,
        intent: PromptIntent,
        *,
        limit: int = 5,
        recent_artists: frozenset[str] = frozenset(),
    ) -> list[Track]:
        # No ranking stage here to feed a diversity signal into -- accepted
        # for interface compatibility with CandidateRetriever, unused.
        del recent_artists
        _ensure_seed_catalog(db)
        if intent.artist:
            rows = _fuzzy_artist_matches(db, intent.artist, limit)
            # A named artist with no good match is reported plainly (empty
            # list) by the caller, never silently replaced by a mood-bucket
            # guess -- the user asked for something specific.
            return [_to_track(row) for row in rows]

        bucket = _mood_bucket_for(intent)
        rows = (
            db.query(CatalogTrack)
            .filter(CatalogTrack.mood_bucket == bucket)
            .order_by(CatalogTrack.id.asc())
            .limit(limit)
            .all()
        )
        if not rows:
            # Safe fallback mirroring the old single local-demo-track
            # fallback: any catalog row, deterministically the oldest.
            rows = db.query(CatalogTrack).order_by(CatalogTrack.id.asc()).limit(limit).all()
        return [_to_track(row) for row in rows]
