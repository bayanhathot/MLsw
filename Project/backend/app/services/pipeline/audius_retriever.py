"""CandidateRetriever implementations wrapping the existing Audius lookup.

Maps audius_service.search_tracks' dicts into the same Track shape the
catalog retriever returns, so all of these are interchangeable behind one
interface.

Two implementations live here:
  * AudiusCandidateRetriever -- the original single-query lookup: forwards
    intent.artist or intent.search_query straight to Audius.
  * MultiQueryAudiusRetriever -- fans out several deterministically-built
    queries (query_planner.build_queries), fuses their ranked results with
    Reciprocal Rank Fusion, then re-ranks the fused pool against the
    structured intent (genre/mood/energy). See VIBE_RECOMMENDATION_DESIGN.md
    for the full rationale; which one is active is a runtime choice made in
    dependencies.py via AUDIUS_RETRIEVER.
"""

import os

from sqlalchemy.orm import Session

from app.schemas import PromptIntent, Track
from app.services.audius_service import get_last_search_cache_hit, search_tracks
from app.services.pipeline.catalog_retriever import _trigram_similarity
from app.services.pipeline.interfaces import CandidateRetriever
from app.services.pipeline.query_planner import build_queries

# Env-overridable knobs for the multi-query path, following the same
# os.getenv(...) pattern ARTIST_MATCH_THRESHOLD uses in catalog_retriever.py.
MAX_QUERIES = int(os.getenv("MAX_QUERIES", "5"))
CANDIDATES_PER_QUERY = int(os.getenv("CANDIDATES_PER_QUERY", "8"))
# Raised from 5: a bigger fused pool (roughly 20-40 raw candidates before
# final ranking, depending on query overlap) gives both the metadata ranker
# and session_manager's played-track exclude-scan real alternatives to work
# with, instead of ranking/excluding within a handful of results.
MIN_POOL_SIZE = int(os.getenv("MIN_POOL_SIZE", "25"))
MAX_RETRIEVAL_ROUNDS = int(os.getenv("MAX_RETRIEVAL_ROUNDS", "3"))
RRF_K = int(os.getenv("RRF_K", "60"))
WEIGHT_RETRIEVAL = float(os.getenv("WEIGHT_RETRIEVAL", "0.3"))
WEIGHT_GENRE = float(os.getenv("WEIGHT_GENRE", "0.2"))
WEIGHT_MOOD = float(os.getenv("WEIGHT_MOOD", "0.1"))
WEIGHT_TAG = float(os.getenv("WEIGHT_TAG", "0.15"))
# Lowered from the original 0.15: a hardcoded genre->energy lookup is a much
# weaker signal than real per-track tag/mood data, so it's also gated to
# only apply when neither of those is available for a given candidate (see
# _score_candidates) -- this weight only matters on the fallback path.
WEIGHT_ENERGY = float(os.getenv("WEIGHT_ENERGY", "0.05"))
# Deliberately the largest weight: a required-artist match ("play george
# wassouf") should reliably outrank a same-or-better-RRF-ranked candidate
# that isn't that artist, without being a hard filter (the existing
# "prefer scoring over hard bans" principle -- see catalog_retriever.py's
# ARTIST_MATCH_THRESHOLD for the one place this codebase does use a hard
# cutoff, for a different reason: reporting "nothing matched" plainly).
WEIGHT_ARTIST_MATCH = float(os.getenv("WEIGHT_ARTIST_MATCH", "0.5"))

# A small hardcoded heuristic table, not a measured value: Audius rarely
# returns per-track energy/BPM data, so this approximates "does this genre
# usually match the requested energy" well enough to weight ranking, without
# claiming to be real per-track analysis (see SegmentSelector's BPM/key
# handling for why that data isn't available here).
_GENRE_ENERGY = {
    "techno": "high",
    "house": "high",
    "hip-hop": "high",
    "rock": "high",
    "electronic": "high",
    "pop": "medium",
    "arabic": "medium",
    "ambient": "low",
    "lofi": "low",
    "classical": "low",
    "jazz": "low",
}


def _to_track(item: dict) -> Track | None:
    if not isinstance(item, dict):
        return None
    audio_url = item.get("audio_url")
    source_track_id = item.get("source_track_id")
    if not isinstance(audio_url, str) or not audio_url.strip():
        return None
    if not isinstance(source_track_id, (str, int)):
        return None
    try:
        duration = max(0, int(item.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    return Track(
        source="audius",
        source_track_id=str(source_track_id),
        title=str(item.get("title") or "Unknown title")[:255],
        artist=str(item.get("artist") or "Unknown artist")[:255],
        album=None,
        audio_url=audio_url,
        cover_url=item.get("cover_url") if isinstance(item.get("cover_url"), str) else None,
        duration_seconds=duration,
        genre=item.get("genre") if isinstance(item.get("genre"), str) else None,
        vibe=item.get("mood") if isinstance(item.get("mood"), str) else None,
        vibe_label=None,
        tags=item.get("tags") if isinstance(item.get("tags"), str) else None,
        catalog_track_id=None,
        local_path=None,
    )


class AudiusCandidateRetriever(CandidateRetriever):
    name = "audius"

    def __init__(self) -> None:
        # Debug-only, best-effort -- see MultiQueryAudiusRetriever's
        # last_candidate_scores docstring for the same statefulness caveat.
        self.last_cache_hit: bool | None = None

    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
        # Audius already does full-text search across its own catalog, so a
        # named artist is just forwarded as the query rather than fuzzy
        # matched client-side.
        query = intent.artist or intent.search_query
        raw_tracks = search_tracks(query, limit=limit)
        self.last_cache_hit = get_last_search_cache_hit()
        tracks: list[Track] = []
        for item in raw_tracks:
            track = _to_track(item)
            if track is not None:
                tracks.append(track)
        return tracks


def _relaxation_rounds(
    queries: list[str], *, round_size: int = 2, max_rounds: int = MAX_RETRIEVAL_ROUNDS
) -> list[list[str]]:
    """Groups queries (already ordered specific-to-general by build_queries)
    into rounds of `round_size`, capped at `max_rounds`. MultiQueryAudiusRetriever
    stops issuing further rounds once the fused pool is big enough, so this
    only defines how far it *can* broaden, not whether it does."""

    rounds: list[list[str]] = []
    for start in range(0, len(queries), round_size):
        if len(rounds) >= max_rounds:
            break
        rounds.append(queries[start : start + round_size])
    return rounds


def _reciprocal_rank_fusion(rank_lists: list[list[str]], *, k: int = RRF_K) -> list[str]:
    """A track that shows up near the top of multiple query result lists
    outranks one that only appeared once, without needing to compare
    Audius's own internal relevance score (not returned/comparable across
    separate search calls) against anything else."""

    scores: dict[str, float] = {}
    for ranked_keys in rank_lists:
        for position, key in enumerate(ranked_keys):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=lambda key: scores[key], reverse=True)


def _score_candidates(
    pool: dict[str, Track], fused_order: list[str], intent: PromptIntent
) -> dict[str, dict[str, float | None]]:
    """Scores every pooled candidate against the intent: one 0..1 sub-signal
    per named component, plus a final weighted-average "total". This is also
    what session_manager.py surfaces in the pipeline debug trace, so a human
    can see *why* a track was picked, not just which one.

    A sub-signal is only included in a candidate's average when both sides
    of the comparison actually have data -- a candidate with no tags at all
    doesn't get a tag_score of 0 dragging its average down, it's just
    excluded from that candidate's normalization; symmetrically, an intent
    with no genre/mood requested doesn't score every candidate's genre/mood
    against nothing, since a candidate that happens to have that metadata
    would otherwise be unfairly penalized relative to one that doesn't.
    total is therefore a weighted *average* over only the signals that were
    actually available, not a weighted sum over all of them -- missing
    metadata reduces confidence, it never counts against a candidate.
    """

    rrf_rank = {key: index for index, key in enumerate(fused_order)}
    n = len(fused_order)
    intent_genres = {genre.lower() for genre in intent.genres}
    intent_mood = intent.mood.lower() if intent.mood and intent.mood != "balanced" else None
    required_artist = (
        intent.artist.lower() if intent.artist and intent.artist_mode == "required" else None
    )
    tag_terms = list(intent_genres) + ([intent_mood] if intent_mood else [])

    breakdown: dict[str, dict[str, float | None]] = {}
    for key, track in pool.items():
        retrieval_score = 1.0 - (rrf_rank[key] / max(n - 1, 1))

        genre_score = None
        if intent_genres and track.genre:
            genre_score = 1.0 if track.genre.lower() in intent_genres else 0.0

        mood_score = None
        if intent_mood and track.vibe:
            mood_score = 1.0 if track.vibe.lower() == intent_mood else 0.0

        tag_score = None
        if tag_terms and track.tags:
            tag_text = track.tags.lower()
            hits = sum(1 for term in tag_terms if term in tag_text)
            tag_score = min(1.0, hits / len(tag_terms))

        # A hardcoded genre->energy lookup table is a much weaker signal
        # than real per-track tag/mood data -- only fall back to it when
        # neither of those is available for this candidate at all, and only
        # when the candidate's genre is actually in the table (distinguishes
        # "no data for this genre" from "checked, energy doesn't match").
        energy_score = None
        if (
            tag_score is None
            and mood_score is None
            and track.genre
            and track.genre.lower() in _GENRE_ENERGY
        ):
            energy_score = 1.0 if _GENRE_ENERGY[track.genre.lower()] == intent.energy else 0.0

        artist_match_score = None
        if required_artist:
            artist_match_score = _trigram_similarity(track.artist.lower(), required_artist)

        signals = (
            (WEIGHT_RETRIEVAL, retrieval_score),
            (WEIGHT_GENRE, genre_score),
            (WEIGHT_MOOD, mood_score),
            (WEIGHT_TAG, tag_score),
            (WEIGHT_ENERGY, energy_score),
            (WEIGHT_ARTIST_MATCH, artist_match_score),
        )
        available = [(weight, score) for weight, score in signals if score is not None]
        weight_sum = sum(weight for weight, _ in available)
        total = (
            sum(weight * score for weight, score in available) / weight_sum if weight_sum else 0.0
        )

        breakdown[key] = {
            "retrieval": retrieval_score,
            "genre": genre_score,
            "mood": mood_score,
            "tag": tag_score,
            "energy": energy_score,
            "artist_match": artist_match_score,
            "total": total,
        }

    return breakdown


def _rank_by_metadata(
    pool: dict[str, Track], fused_order: list[str], intent: PromptIntent
) -> tuple[list[str], dict[str, dict[str, float | None]]]:
    """Re-ranks the RRF-fused order using the structured intent, since RRF
    alone only reflects "how findable was this," not "does it actually match
    the vibe." Returns both the ranked key order and the full per-candidate
    score breakdown (see _score_candidates) so callers can also use it for
    debug observability, not just ranking."""

    breakdown = _score_candidates(pool, fused_order, intent)
    ranked = sorted(pool.keys(), key=lambda key: breakdown[key]["total"], reverse=True)
    return ranked, breakdown


class MultiQueryAudiusRetriever(CandidateRetriever):
    name = "audius_multi_query"

    def __init__(self) -> None:
        # Debug-only, best-effort: the score breakdown from the most recent
        # retrieve() call, keyed by "source:source_track_id", read back by
        # session_manager.py for the pipeline debug trace. This is instance
        # state on an otherwise-stateless singleton (dependencies.py binds
        # one shared instance per process) -- under concurrent requests, a
        # debug trace can race and show another request's breakdown, or be
        # briefly empty. Acceptable here because it's opt-in
        # (ENABLE_PIPELINE_DEBUG) internal observability only, never
        # consulted by retrieval/ranking itself.
        self.last_candidate_scores: dict[str, dict[str, float | None]] = {}
        # Same debug-only, best-effort caveat as last_candidate_scores above:
        # True if *any* of this call's underlying search_tracks calls was
        # served from cache (see audius_service.py), not every one of them.
        self.last_cache_hit: bool | None = None

    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
        self.last_candidate_scores = {}
        self.last_cache_hit = False
        queries = build_queries(intent, max_queries=MAX_QUERIES)
        pool: dict[str, Track] = {}
        rank_lists: list[list[str]] = []

        for round_queries in _relaxation_rounds(queries, max_rounds=MAX_RETRIEVAL_ROUNDS):
            for query in round_queries:
                raw = search_tracks(query, limit=CANDIDATES_PER_QUERY)
                if get_last_search_cache_hit():
                    self.last_cache_hit = True
                keys: list[str] = []
                for item in raw:
                    track = _to_track(item)
                    if track is None:
                        continue
                    key = f"{track.source}:{track.source_track_id}"
                    pool[key] = track
                    keys.append(key)
                if keys:
                    rank_lists.append(keys)
            if len(pool) >= MIN_POOL_SIZE:
                break

        if not pool:
            return []

        fused_order = _reciprocal_rank_fusion(rank_lists, k=RRF_K)
        ranked, breakdown = _rank_by_metadata(pool, fused_order, intent)
        self.last_candidate_scores = breakdown
        return [pool[key] for key in ranked[:limit]]
