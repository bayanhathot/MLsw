"""The one piece of shared plumbing both sessions and mixes route through:
turn an Intent into Track candidates via whichever CandidateRetriever is
bound, with one consistent "nothing matched" signal instead of either
surface silently substituting something unrelated.

Segment selection, transition planning, and rendering are called directly
against their interfaces by session_manager.py/mix_service.py, since a
session (one current track, updated over many requests) and a mix (several
tracks rendered together in one request) shape those calls differently.

retrieve_candidates_with_fallback is deliberately not fully
retriever-agnostic: it knows about the local catalog's score breakdown
shape (via catalog_retriever.is_strong_catalog_match) and its last-resort
"any row" tier, since dependencies.py wires the local catalog as `primary`
for both sessions and mixes (ai-dj-segment-metadata-architecture.md §12) --
a naive empty-vs-nonempty fallback trigger would let the catalog's own
"give up gracefully, return any row" behavior look like success and never
consult Audius at all for most vibe-only prompts.
"""

from sqlalchemy.orm import Session

from app.schemas import PromptIntent, Track
from app.services.pipeline.catalog_retriever import (
    LAST_RESORT_CATALOG_RETRIEVER,
    is_strong_catalog_match,
    last_resort_tracks,
)
from app.services.pipeline.interfaces import CandidateRetriever


class NoMatchingCandidate(Exception):
    """A CandidateRetriever found nothing above its match threshold."""


def _track_key(track: Track) -> str:
    return f"{track.source}:{track.source_track_id}"


def _primary_is_strong(
    candidates: list[Track], breakdown: dict[str, dict[str, float | None]]
) -> bool:
    """Whether `primary`'s own top-ranked candidate is trustworthy enough to
    serve directly -- see catalog_retriever.is_strong_catalog_match for what
    "trustworthy" means for the catalog specifically. `breakdown` is this
    call's own score breakdown (see _retrieve_primary_with_breakdown) --
    deliberately not read back off the retriever instance after the fact:
    CatalogTrackRetriever is a shared singleton across concurrent requests
    (see its last_candidate_scores docstring), and this decision needs THIS
    call's own scores, not whichever concurrent request's retrieve() call
    happened to run last. An empty breakdown (e.g. Audius, if ever used as
    `primary`, has no scored variant) is treated as strong whenever it
    returned anything at all -- unscored empty-vs-nonempty is the only
    signal retrieve_candidates already uses for it, and this shouldn't
    second-guess that."""

    if not breakdown:
        return True
    return is_strong_catalog_match(breakdown.get(_track_key(candidates[0])))


def retrieve_candidates(
    db: Session,
    intent: PromptIntent,
    retriever: CandidateRetriever,
    *,
    limit: int = 5,
    recent_artists: frozenset[str] = frozenset(),
    viewer_id: int | None = None,
) -> list[Track]:
    candidates = retriever.retrieve(
        db, intent, limit=limit, recent_artists=recent_artists, viewer_id=viewer_id
    )
    if not candidates:
        raise NoMatchingCandidate(
            f"No {retriever.name} candidate matched this request closely enough."
        )
    return candidates


def _retrieve_primary_with_breakdown(
    db: Session,
    intent: PromptIntent,
    primary: CandidateRetriever,
    *,
    limit: int,
    recent_artists: frozenset[str],
    viewer_id: int | None,
) -> tuple[list[Track], dict[str, dict[str, float | None]]]:
    """Like retrieve_candidates, but also returns `primary`'s per-call score
    breakdown when it has one (CatalogTrackRetriever.retrieve_with_scores),
    scoped to this call -- see _primary_is_strong for why that matters.
    Retrievers without a scored variant (e.g. Audius) fall back to the bare
    CandidateRetriever interface and an empty breakdown."""

    retrieve_with_scores = getattr(primary, "retrieve_with_scores", None)
    if retrieve_with_scores is None:
        candidates = primary.retrieve(
            db, intent, limit=limit, recent_artists=recent_artists, viewer_id=viewer_id
        )
        breakdown: dict[str, dict[str, float | None]] = {}
    else:
        candidates, breakdown = retrieve_with_scores(
            db, intent, limit=limit, recent_artists=recent_artists, viewer_id=viewer_id
        )
    if not candidates:
        raise NoMatchingCandidate(
            f"No {primary.name} candidate matched this request closely enough."
        )
    return candidates, breakdown


def retrieve_candidates_with_fallback(
    db: Session,
    intent: PromptIntent,
    primary: CandidateRetriever,
    fallback: CandidateRetriever,
    *,
    limit: int = 5,
    recent_artists: frozenset[str] = frozenset(),
    viewer_id: int | None = None,
) -> tuple[list[Track], CandidateRetriever]:
    """Four tiers, tried in order, mirroring the retry -> cheaper fallback
    -> hard cut -> "something is always queued" shape
    ai-dj-segment-metadata-architecture.md §4.5 uses for prepared_transition
    failure handling:

    1. `primary` -- served directly only when it found something *and*
       that top match is strong enough to trust (_primary_is_strong).
    2. `fallback` -- tried whenever primary came back empty or weak.
    3. `primary`'s own weak-but-real candidates (if it found any) -- once
       `fallback` also comes back empty, a weak-but-real match is still a
       legitimate, intent-matched result, and strictly better than the
       intent-blind tier below. Only tier 1 skipped serving it outright to
       give `fallback` a chance to do better first.
    4. The local catalog's own last-resort "any row" tier
       (catalog_retriever.last_resort_tracks) -- tried only once `primary`
       found genuinely *nothing* (not just weak) and `fallback` also came
       back empty. Only for a no-artist request: a named artist absent
       everywhere is reported plainly instead (CandidateRetriever's own
       "report plainly, never substitute an unrelated candidate" contract
       -- same reason CatalogTrackRetriever.retrieve()'s artist branch has
       never had an any-row fallback of its own). This is what used to be
       CatalogTrackRetriever.retrieve()'s own internal no-artist-branch
       behavior; it's an explicit tier here instead so a weak/empty
       primary+fallback still raises NoMatchingCandidate through tiers 1-3
       rather than that giving-up-gracefully behavior masquerading as a
       real match.

    Returns which retriever actually served the candidates, since callers
    persist that alongside the result (e.g. DJSession.retriever_name) so a
    later re-resolution knows what actually served last time -- tier 4
    reports LAST_RESORT_CATALOG_RETRIEVER, a distinct object from the real
    catalog singleton (`primary`, once dependencies.py wires it that way),
    so identity-based fell_back checks in session_manager.py still read
    True for it (tier 3 reports `primary` itself, correctly reading False --
    it's still primary's own match, not a fallback). Raises
    NoMatchingCandidate only when every tier, including the last-resort
    one, comes back empty -- e.g. a named artist matched nowhere, or an
    empty catalog table with no visible rows at all."""

    primary_candidates: list[Track] = []
    primary_breakdown: dict[str, dict[str, float | None]] = {}
    try:
        primary_candidates, primary_breakdown = _retrieve_primary_with_breakdown(
            db, intent, primary, limit=limit, recent_artists=recent_artists, viewer_id=viewer_id
        )
        if _primary_is_strong(primary_candidates, primary_breakdown):
            # Best-effort write for session_manager.py's debug trace only
            # (getattr(served_by, "last_candidate_scores", {}).get(...)) --
            # _retrieve_primary_with_breakdown called retrieve_with_scores
            # directly rather than retrieve(), specifically so the
            # strong/weak decision above never reads this attribute back;
            # writing it here doesn't undo that, it just keeps the debug
            # trace showing this request's own breakdown instead of
            # whatever an unrelated concurrent request last left behind.
            if hasattr(primary, "last_candidate_scores"):
                primary.last_candidate_scores = primary_breakdown
            return primary_candidates, primary
    except NoMatchingCandidate:
        pass

    try:
        return (
            retrieve_candidates(
                db, intent, fallback, limit=limit, recent_artists=recent_artists, viewer_id=viewer_id
            ),
            fallback,
        )
    except NoMatchingCandidate:
        pass

    if primary_candidates:
        if hasattr(primary, "last_candidate_scores"):
            primary.last_candidate_scores = primary_breakdown
        return primary_candidates, primary

    if not intent.artist:
        last_resort = last_resort_tracks(db, viewer_id=viewer_id, limit=limit)
        if last_resort:
            return last_resort, LAST_RESORT_CATALOG_RETRIEVER

    raise NoMatchingCandidate(
        f"No {primary.name} or {fallback.name} candidate matched this request closely enough, "
        "and the catalog had nothing left to serve as a last resort either."
    )
