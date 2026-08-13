"""The one piece of shared plumbing both sessions and mixes route through:
turn an Intent into Track candidates via whichever CandidateRetriever is
bound, with one consistent "nothing matched" signal instead of either
surface silently substituting something unrelated.

Segment selection, transition planning, and rendering are called directly
against their interfaces by session_manager.py/mix_service.py, since a
session (one current track, updated over many requests) and a mix (several
tracks rendered together in one request) shape those calls differently.
"""

from sqlalchemy.orm import Session

from app.schemas import PromptIntent, Track
from app.services.pipeline.interfaces import CandidateRetriever


class NoMatchingCandidate(Exception):
    """A CandidateRetriever found nothing above its match threshold."""


def retrieve_candidates(
    db: Session, intent: PromptIntent, retriever: CandidateRetriever, *, limit: int = 5
) -> list[Track]:
    candidates = retriever.retrieve(db, intent, limit=limit)
    if not candidates:
        raise NoMatchingCandidate(
            f"No {retriever.name} candidate matched this request closely enough."
        )
    return candidates


def retrieve_candidates_with_fallback(
    db: Session,
    intent: PromptIntent,
    primary: CandidateRetriever,
    fallback: CandidateRetriever,
    *,
    limit: int = 5,
) -> tuple[list[Track], CandidateRetriever]:
    """Tries `primary` first; only falls through to `fallback` when primary
    plainly found nothing (an empty list is never silently replaced with an
    unrelated result -- same "report plainly" guarantee as
    retrieve_candidates, just with one more retriever to try before giving
    up). Returns which retriever actually served the candidates, since
    callers persist that alongside the result (e.g. DJSession.retriever_name)
    so a later re-resolution knows what actually served last time. Raises
    NoMatchingCandidate only when both retrievers come back empty."""

    try:
        return retrieve_candidates(db, intent, primary, limit=limit), primary
    except NoMatchingCandidate:
        pass
    try:
        return retrieve_candidates(db, intent, fallback, limit=limit), fallback
    except NoMatchingCandidate:
        raise NoMatchingCandidate(
            f"No {primary.name} or {fallback.name} candidate matched this request closely enough."
        ) from None
