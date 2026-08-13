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
from app.services.audius_service import search_tracks
from app.services.pipeline.interfaces import CandidateRetriever
from app.services.pipeline.query_planner import build_queries

# Env-overridable knobs for the multi-query path, following the same
# os.getenv(...) pattern ARTIST_MATCH_THRESHOLD uses in catalog_retriever.py.
MAX_QUERIES = int(os.getenv("MAX_QUERIES", "5"))
CANDIDATES_PER_QUERY = int(os.getenv("CANDIDATES_PER_QUERY", "5"))
MIN_POOL_SIZE = int(os.getenv("MIN_POOL_SIZE", "5"))
MAX_RETRIEVAL_ROUNDS = int(os.getenv("MAX_RETRIEVAL_ROUNDS", "3"))
RRF_K = int(os.getenv("RRF_K", "60"))
WEIGHT_RETRIEVAL = float(os.getenv("WEIGHT_RETRIEVAL", "0.4"))
WEIGHT_GENRE = float(os.getenv("WEIGHT_GENRE", "0.3"))
WEIGHT_MOOD = float(os.getenv("WEIGHT_MOOD", "0.15"))
WEIGHT_ENERGY = float(os.getenv("WEIGHT_ENERGY", "0.15"))

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
        catalog_track_id=None,
        local_path=None,
    )


class AudiusCandidateRetriever(CandidateRetriever):
    name = "audius"

    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
        # Audius already does full-text search across its own catalog, so a
        # named artist is just forwarded as the query rather than fuzzy
        # matched client-side.
        query = intent.artist or intent.search_query
        raw_tracks = search_tracks(query, limit=limit)
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


def _genre_energy_match(genre: str | None, energy: str) -> float:
    if not genre:
        return 0.0
    return 1.0 if _GENRE_ENERGY.get(genre.lower()) == energy else 0.0


def _rank_by_metadata(
    pool: dict[str, Track], fused_order: list[str], intent: PromptIntent
) -> list[str]:
    """Re-ranks the RRF-fused order using the structured intent, since RRF
    alone only reflects "how findable was this," not "does it actually match
    the vibe." All four sub-scores are normalized to 0..1 before weighting,
    so a hand-tuned weight means what it says instead of being dominated by
    whichever raw signal happens to have the widest range."""

    rrf_rank = {key: index for index, key in enumerate(fused_order)}
    n = len(fused_order)
    intent_genres = {genre.lower() for genre in intent.genres}

    def score(key: str) -> float:
        track = pool[key]
        retrieval_score = 1.0 - (rrf_rank[key] / max(n - 1, 1))
        genre_score = 1.0 if track.genre and track.genre.lower() in intent_genres else 0.0
        mood_score = (
            1.0 if track.vibe and intent.mood and track.vibe.lower() == intent.mood.lower() else 0.0
        )
        energy_score = _genre_energy_match(track.genre, intent.energy)

        return (
            WEIGHT_RETRIEVAL * retrieval_score
            + WEIGHT_GENRE * genre_score
            + WEIGHT_MOOD * mood_score
            + WEIGHT_ENERGY * energy_score
        )

    return sorted(pool.keys(), key=score, reverse=True)


class MultiQueryAudiusRetriever(CandidateRetriever):
    name = "audius_multi_query"

    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
        queries = build_queries(intent, max_queries=MAX_QUERIES)
        pool: dict[str, Track] = {}
        rank_lists: list[list[str]] = []

        for round_queries in _relaxation_rounds(queries, max_rounds=MAX_RETRIEVAL_ROUNDS):
            for query in round_queries:
                raw = search_tracks(query, limit=CANDIDATES_PER_QUERY)
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
        ranked = _rank_by_metadata(pool, fused_order, intent)
        return [pool[key] for key in ranked[:limit]]
