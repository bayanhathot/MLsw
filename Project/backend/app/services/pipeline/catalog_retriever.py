"""CandidateRetriever backed by the real, Postgres-resident catalog_tracks
table -- this is what the old hardcoded 4-track TRACKS dict became.

Two matching strategies:
  * intent.artist is set -> fuzzy-match it against CatalogTrack.artist using
    Postgres pg_trgm similarity() (falls back to an equivalent pure-Python
    trigram-Jaccard similarity on any other SQL dialect, notably the SQLite
    engine the test suite uses -- see _trigram_similarity). Below
    ARTIST_MATCH_THRESHOLD this returns an empty list rather than a guess --
    requirement 8's "report that plainly" behavior.
  * no artist named -> a broader visibility-filtered pool (capped at
    NO_ARTIST_CANDIDATE_POOL_CAP), every row of which gets scored on
    whatever signals it actually has -- genre for a real upload, the old
    energy/vocals/mood-bucket keyword rules (via mood_bucket) for a seeded
    row. Deliberately not a hard SQL filter to one mood_bucket: that would
    exclude every real upload from this branch entirely, since real
    uploads never have mood_bucket set (see _score_rows).

Whatever a query above returns gets scored (_score_rows) and ranked, but
`retrieve()` never guarantees a *good* match, only a real one -- see
CATALOG_MATCH_THRESHOLD/is_strong_catalog_match, which
orchestrator.retrieve_candidates_with_fallback uses to decide whether this
retriever's result is trustworthy enough to serve directly or whether Audius
still deserves a look. The old "no rows matched -> return any row anyway"
last-resort behavior no longer lives here: it moved out to
orchestrator.py's own last-resort tier (last_resort_tracks below), tried
only once *both* sources have come back weak or empty -- see
ai-dj-segment-metadata-architecture.md §12.1.
"""

import logging
import os
import shutil
from pathlib import Path

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.database.models.catalog import CatalogTrack
from app.schemas import PromptIntent, Track
from app.services import upload_queue
from app.services.pipeline.interfaces import CandidateRetriever

logger = logging.getLogger(__name__)

CATALOG_AUDIO_SUBDIR = "catalog"
ARTIST_MATCH_THRESHOLD = float(os.getenv("ARTIST_MATCH_THRESHOLD", "0.3"))

# Env-overridable ranking weights, following the same os.getenv(...)
# pattern audius_retriever.py's WEIGHT_* knobs use -- prefixed WEIGHT_CATALOG_
# rather than reusing those names, since both modules' weights are read
# independently and a shared name would let tuning one retriever silently
# retune the other. Mirrors audius_retriever._score_candidates' weighted-
# average-of-available-signals shape (see _score_rows below), not its exact
# fields -- there's no RRF/retrieval_score equivalent here, since these
# weights only ever rank rows a query already filtered (the artist-fuzzy-match
# threshold or the mood-bucket keyword match), never a fused multi-query pool.
WEIGHT_CATALOG_GENRE = float(os.getenv("WEIGHT_CATALOG_GENRE", "0.2"))
WEIGHT_CATALOG_MOOD = float(os.getenv("WEIGHT_CATALOG_MOOD", "0.1"))
# Deliberately the largest weight, same reasoning as audius_retriever's
# WEIGHT_ARTIST_MATCH: a required-artist match should reliably outrank a
# same-bucket/same-genre candidate that isn't that artist.
WEIGHT_CATALOG_ARTIST_MATCH = float(os.getenv("WEIGHT_CATALOG_ARTIST_MATCH", "0.5"))

# Same env-var convention as ARTIST_MATCH_THRESHOLD -- a number to tune once
# real usage exists, not a value this module should over-tune from theory
# alone (see ai-dj-segment-metadata-architecture.md §12.1). Gates whether
# orchestrator.retrieve_candidates_with_fallback serves this retriever's top
# match directly or still consults Audius -- see is_strong_catalog_match.
CATALOG_MATCH_THRESHOLD = float(os.getenv("CATALOG_MATCH_THRESHOLD", "0.5"))

# Bounds the no-artist candidate pool retrieve_with_scores pulls for
# scoring (see its no-artist branch below) -- this project's scale doesn't
# need real pagination, but querying the whole table unbounded isn't
# warranted either. Generous enough that a genuine genre/mood match well
# past the first `limit` rows by insertion order still gets considered;
# ordered by id purely for a deterministic query, not a ranking signal --
# ranking happens after scoring, via `total`.
NO_ARTIST_CANDIDATE_POOL_CAP = int(os.getenv("NO_ARTIST_CANDIDATE_POOL_CAP", "300"))

# The 4 seeded demo rows (migration data insert) point at this repo-bundled
# asset -- the same file the old TRACKS dict used for every bucket -- rather
# than something already sitting in UPLOAD_DIR. It's staged into place on
# first use instead of at migration time, since UPLOAD_DIR is an
# environment-resolved runtime path (tests monkeypatch it per-run).
_SEED_AUDIO_SOURCE = Path(__file__).resolve().parents[2] / "static" / "audio" / "cuemix-demo.wav"

# Canonical content for the 4 legacy TRACKS-dict rows. The Alembic migration
# inserts these for a real `alembic upgrade head` deployment; this module
# additionally self-heals an empty table (e.g. a database whose schema was
# created straight from SQLAlchemy metadata rather than via migrations, as
# the test suite's SQLite engine does) so the catalog retriever always has
# something to match against.
_SEED_TRACKS = [
    {"title": "Momentum Loop", "artist": "Cuemix AI DJ", "album": "Workout Demo Catalog", "mood_bucket": "energy", "vibe_label": "Gym energy", "visibility": "public"},
    {"title": "Midnight Whispers", "artist": "Cuemix AI DJ", "album": "Vocal Demo Catalog", "mood_bucket": "vocals", "vibe_label": "Emotional vocals", "visibility": "public"},
    {"title": "Focus Loop 01", "artist": "Cuemix AI DJ", "album": "Focus Demo Catalog", "mood_bucket": "focus", "vibe_label": "Deep work focus", "visibility": "public"},
    {"title": "Smooth Flow Demo", "artist": "Cuemix AI DJ", "album": "General Demo Catalog", "mood_bucket": "smooth", "vibe_label": "Smooth flow", "visibility": "public"},
]


def _ensure_seed_catalog(db: Session) -> None:
    if db.query(CatalogTrack.id).first() is not None:
        return
    for seed in _SEED_TRACKS:
        db.add(
            CatalogTrack(
                **seed,
                storage_name="cuemix-demo.wav",
                content_type="audio/wav",
                duration_seconds=60,
                # Not "completed": that means "librosa actually analyzed
                # this and here's what it found" (see audio_analysis.py,
                # which always sets bpm/musical_key in the same commit as
                # "completed") -- these 4 rows never went through real
                # analysis at all. "not_applicable" is the accepted,
                # already-modeled status for exactly this (see the
                # analysis_status CHECK constraint / schemas.py's Literal);
                # segment_start/end below are still authoritative for these
                # rows (deliberately chosen at seed time, not analysis
                # output) -- see segment_selector.py's matching
                # analysis_status check.
                analysis_status="not_applicable",
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


def _fuzzy_artist_matches(
    db: Session, artist: str, limit: int, viewer_id: int | None
) -> list[CatalogTrack]:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        similarity = func.similarity(CatalogTrack.artist, artist)
        return (
            _visibility_filter(db.query(CatalogTrack), viewer_id)
            .filter(similarity >= ARTIST_MATCH_THRESHOLD)
            .order_by(similarity.desc(), CatalogTrack.id.asc())
            .limit(limit)
            .all()
        )

    # No pg_trgm outside Postgres: an equivalent deterministic Python-side
    # similarity over the catalog. Fine at this table's scale; not a ranking
    # model (it's a single, unlearned string-similarity function).
    candidates = _visibility_filter(db.query(CatalogTrack), viewer_id).all()
    scored = [(row, _trigram_similarity(row.artist, artist)) for row in candidates]
    scored = [item for item in scored if item[1] >= ARTIST_MATCH_THRESHOLD]
    scored.sort(key=lambda item: (-item[1], item[0].id))
    return [row for row, _ in scored[:limit]]


def _score_rows(
    rows: list[CatalogTrack], intent: PromptIntent
) -> dict[str, dict[str, float | None]]:
    """Scores already-queried catalog rows against the intent: one 0..1
    sub-signal per named component, plus a final weighted-average "total" --
    same weighted-average-of-available-signals shape as
    audius_retriever._score_candidates (see its docstring for the full
    rationale: a missing signal is excluded from a candidate's average, not
    scored 0, so missing metadata never counts against a candidate on either
    side of the comparison).

    Only ever called on rows a query already filtered (_fuzzy_artist_matches'
    ARTIST_MATCH_THRESHOLD cutoff, or the mood-bucket keyword match) --
    this reorders and annotates that set, it never expands or re-filters it.
    """

    intent_genres = {genre.lower() for genre in intent.genres}
    required_artist = intent.artist.lower() if intent.artist else None
    # mood_bucket's 4 values (energy/vocals/focus/smooth) aren't the same
    # vocabulary as intent.mood's free-text field -- _mood_bucket_for is the
    # existing (and only) mapping from an intent to that vocabulary, already
    # used to build the no-artist query above, so reusing it here keeps this
    # signal honest rather than inventing a second, inconsistent mapping.
    target_bucket = _mood_bucket_for(intent)

    breakdown: dict[str, dict[str, float | None]] = {}
    for row in rows:
        genre_score = None
        if intent_genres and row.genre:
            genre_score = 1.0 if row.genre.lower() in intent_genres else 0.0

        # mood_bucket is only ever populated on the 4 seeded rows (and rows
        # explicitly set up that way, e.g. cold-seed data) -- a real upload
        # has none, so this signal is honestly excluded for it rather than
        # backfilled to a guessed bucket.
        mood_score = None
        if row.mood_bucket:
            mood_score = 1.0 if row.mood_bucket == target_bucket else 0.0

        artist_score = None
        if required_artist:
            artist_score = _trigram_similarity(row.artist.lower(), required_artist)

        signals = (
            (WEIGHT_CATALOG_GENRE, genre_score),
            (WEIGHT_CATALOG_MOOD, mood_score),
            (WEIGHT_CATALOG_ARTIST_MATCH, artist_score),
        )
        available = [(weight, score) for weight, score in signals if score is not None]
        weight_sum = sum(weight for weight, _ in available)
        total = (
            sum(weight * score for weight, score in available) / weight_sum if weight_sum else 0.0
        )

        breakdown[f"catalog:{row.id}"] = {
            "genre": genre_score,
            "mood": mood_score,
            "artist_match": artist_score,
            "total": total,
        }

    return breakdown


def is_strong_catalog_match(entry: dict[str, float | None] | None) -> bool:
    """Whether one _score_rows breakdown entry is trustworthy enough to
    serve directly, without also consulting Audius -- see
    orchestrator.retrieve_candidates_with_fallback.

    Deliberately requires genre or artist_match to be present, not just a
    CATALOG_MATCH_THRESHOLD-clearing `total`. `total` is a weighted
    *average* of only the available signals (see _score_rows), which means
    a candidate with mood_score as its *only* available signal always
    averages to exactly that signal's own score, regardless of
    WEIGHT_CATALOG_MOOD -- a perfect mood_bucket match alone reaches
    total=1.0 the same way a perfect genre match would. mood_bucket is
    populated on 4 curated seed rows and nothing else (see _score_rows'
    mood_score comment), so treating that alone as "strong" would mean
    *any* no-artist, no-genre prompt matches one of the 4 buckets and never
    reaches Audius again -- reintroducing the exact bug the historical
    Audius-primary swap fixed (see
    ai-dj-segment-metadata-architecture.md §12, and
    test_generic_vibe_prompt_with_no_artist_now_reaches_audius_first's
    original docstring). genre (real, user-typed on real uploads) and a
    required-artist match are specific enough to trust alone; a coarse
    4-bucket keyword heuristic is not.
    """

    if entry is None:
        return False
    if entry.get("genre") is None and entry.get("artist_match") is None:
        return False
    total = entry.get("total")
    return total is not None and total >= CATALOG_MATCH_THRESHOLD


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
        cover_url=public_api_url(f"/catalog/tracks/{row.id}/cover") if row.cover_storage_name else None,
        duration_seconds=row.duration_seconds,
        genre=row.genre,
        vibe=row.mood_bucket,
        vibe_label=row.vibe_label,
        catalog_track_id=row.id,
        local_path=str(_track_local_path(row)),
    )


def _visibility_filter(query, viewer_id: int | None):
    """A session can only ever be served a catalog track that's public, or
    owned by the session's own viewer -- see
    ai-dj-segment-metadata-architecture.md §12.2. A guest session
    (viewer_id is None) only ever sees public tracks; there's no owner to
    match against."""

    if viewer_id is None:
        return query.filter(CatalogTrack.visibility == "public")
    return query.filter(
        or_(CatalogTrack.visibility == "public", CatalogTrack.owner_id == viewer_id)
    )


class CatalogTrackRetriever(CandidateRetriever):
    name = "catalog"

    def __init__(self) -> None:
        # Debug-only, best-effort, and -- as of retrieve_with_scores below --
        # no longer read by anything that makes a real decision.
        # CatalogTrackRetriever is a shared singleton (dependencies.py's
        # _catalog_retriever, bound to every session/mix request), so two
        # concurrent requests' retrieve() calls interleave freely: request
        # A's retrieve() writes here, request B's retrieve() can overwrite
        # it before A's caller reads it back. That was always true, and was
        # always fine for what this was originally used for -- read back
        # only after a request's own retrieval finished, to populate
        # session_manager.py's debug trace, where a race at worst shows the
        # wrong "why" in a debug panel someone is looking at, not a wrong
        # decision. It stopped being fine the moment
        # orchestrator._primary_is_strong needed this data for a real
        # control-flow decision (serve the catalog's match directly vs.
        # also consult Audius) -- reading shared state back after the fact
        # would have meant that decision could silently use a *different*
        # request's scores under real concurrent traffic. retrieve_with_scores
        # returns the breakdown scoped to its own call instead, and
        # orchestrator.py uses that; this attribute now exists purely for
        # the debug trace, and nothing here needs to change that unless the
        # debug trace stops needing it.
        self.last_candidate_scores: dict[str, dict[str, float | None]] = {}

    def retrieve_with_scores(
        self,
        db: Session,
        intent: PromptIntent,
        *,
        limit: int = 5,
        recent_artists: frozenset[str] = frozenset(),
        viewer_id: int | None = None,
    ) -> tuple[list[Track], dict[str, dict[str, float | None]]]:
        """Same matching/scoring/ranking as retrieve(), but returns this
        call's own score breakdown directly instead of only stashing it on
        self.last_candidate_scores -- see that attribute's docstring for
        why a caller that needs the breakdown for anything beyond the debug
        trace (orchestrator._primary_is_strong) must use this instead."""

        # No diversity signal to feed here -- accepted for interface
        # compatibility with CandidateRetriever, unused.
        del recent_artists
        _ensure_seed_catalog(db)
        if intent.artist:
            rows = _fuzzy_artist_matches(db, intent.artist, limit, viewer_id)
            # A named artist with no good match is reported plainly (empty
            # list) by the caller, never silently replaced by a mood-bucket
            # guess -- the user asked for something specific. The
            # ARTIST_MATCH_THRESHOLD cutoff already happened inside
            # _fuzzy_artist_matches; scoring below only re-ranks whatever
            # passed it, it never rescues a row that didn't.
            if not rows:
                return [], {}
            breakdown = _score_rows(rows, intent)
            rows.sort(key=lambda row: breakdown[f"catalog:{row.id}"]["total"], reverse=True)
            return [_to_track(row) for row in rows], breakdown

        # Deliberately not filtered to CatalogTrack.mood_bucket == bucket:
        # mood_bucket is only ever populated on the 4 seeded rows (see
        # _score_rows' mood_score comment) -- a hard SQL filter on it would
        # exclude every real upload from this branch entirely, regardless
        # of how well its genre matches, since real uploads have no
        # mood_bucket at all. Pulling a broader pool and letting
        # _score_rows judge each row on whatever signals it actually has
        # (genre for a real upload, mood_bucket for a seed row) is what
        # lets a real upload's genre match win here, not just a named-artist
        # search. NO_ARTIST_CANDIDATE_POOL_CAP bounds this query; ranking
        # by `total` happens *after* scoring the whole pool, then `limit`
        # slices the ranked result -- scoring after limiting would silently
        # drop a better-matching row past the first `limit` by insertion
        # order (the bug _fuzzy_artist_matches' Postgres path never had,
        # since it orders by similarity before limiting).
        rows = (
            _visibility_filter(db.query(CatalogTrack), viewer_id)
            .order_by(CatalogTrack.id.asc())
            .limit(NO_ARTIST_CANDIDATE_POOL_CAP)
            .all()
        )
        # No "any row anyway" fallback here anymore when the pool is empty
        # -- an empty list is reported plainly, same as the artist branch
        # above. See last_resort_tracks below for where that behavior
        # moved to.
        if not rows:
            return [], {}
        breakdown = _score_rows(rows, intent)
        rows.sort(key=lambda row: breakdown[f"catalog:{row.id}"]["total"], reverse=True)
        selected = rows[:limit]
        selected_breakdown = {
            f"catalog:{row.id}": breakdown[f"catalog:{row.id}"] for row in selected
        }
        return [_to_track(row) for row in selected], selected_breakdown

    def retrieve(
        self,
        db: Session,
        intent: PromptIntent,
        *,
        limit: int = 5,
        recent_artists: frozenset[str] = frozenset(),
        viewer_id: int | None = None,
    ) -> list[Track]:
        tracks, breakdown = self.retrieve_with_scores(
            db, intent, limit=limit, recent_artists=recent_artists, viewer_id=viewer_id
        )
        # Debug-only, best-effort -- see last_candidate_scores' docstring.
        self.last_candidate_scores = breakdown
        return tracks


# A second CatalogTrackRetriever instance, used only as
# orchestrator.retrieve_candidates_with_fallback's last-resort-tier
# `served_by` marker -- same class as the real singleton (dependencies.py's
# `_catalog_retriever`), so `.name` ("catalog") and
# `type(...).__name__` ("CatalogTrackRetriever") read identically in the
# pipeline debug trace / persisted `DJSession.retriever_name`, but a
# genuinely distinct object. That distinctness matters:
# session_manager.py's `fell_back = served_by is not retriever` check needs
# to read True for a last-resort pick (it did fall through past the
# primary's own scored match, even though both are catalog-sourced), which
# plain identity against the primary singleton can't express on its own.
# Never call .retrieve() on this instance -- last_resort_tracks() below is
# the only thing that ever produces its candidates.
LAST_RESORT_CATALOG_RETRIEVER = CatalogTrackRetriever()


def last_resort_tracks(
    db: Session, *, viewer_id: int | None = None, limit: int = 5
) -> list[Track]:
    """Any visible catalog row, deterministically the oldest -- the old
    "no rows matched -> return any row anyway" behavior, relocated here
    from CatalogTrackRetriever.retrieve()'s no-artist branch. Not ranked,
    not filtered by mood/genre/artist: this is the absolute floor of
    orchestrator.retrieve_candidates_with_fallback's tier chain, tried only
    once catalog's own scored match *and* Audius have both come back weak
    or empty -- "something is always queued" rather than a session/mix
    ever hard-failing on a generic request
    (ai-dj-segment-metadata-architecture.md §4.5/§12.1). Still
    visibility-filtered: a private track is never a valid last resort for
    anyone but its owner.
    """

    _ensure_seed_catalog(db)
    rows = (
        _visibility_filter(db.query(CatalogTrack), viewer_id)
        .order_by(CatalogTrack.id.asc())
        .limit(limit)
        .all()
    )
    return [_to_track(row) for row in rows]
