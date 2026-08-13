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
