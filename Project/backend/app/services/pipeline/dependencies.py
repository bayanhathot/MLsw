"""FastAPI Depends() providers for the AI-DJ pipeline stages.

Swapping a stage's implementation later is a one-line change to the provider
function it's bound to here -- nothing that calls Depends(get_x) needs to
change. Sessions default to the catalog retriever and mixes default to
Audius, matching each surface's existing behavior; either can be repointed
independently.
"""

from app.services.pipeline.audio_renderer import PydubAudioRenderer
from app.services.pipeline.audius_retriever import AudiusCandidateRetriever
from app.services.pipeline.catalog_retriever import CatalogTrackRetriever
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)
from app.services.pipeline.segment_selector import LibrosaSegmentSelector
from app.services.pipeline.transition_planner import DeterministicTransitionPlanner
from app.services.pipeline.vibe import DeterministicVibeUnderstander

# Stateless singletons: every implementation only takes a `db: Session` per
# call, so one shared instance per process is enough.
_vibe_understander = DeterministicVibeUnderstander()
_catalog_retriever = CatalogTrackRetriever()
_audius_retriever = AudiusCandidateRetriever()
_segment_selector = LibrosaSegmentSelector()
_transition_planner = DeterministicTransitionPlanner()
_audio_renderer = PydubAudioRenderer()

# Looked up by DJSession.retriever_name so feedback re-invokes whichever
# CandidateRetriever originally served that session (requirement 4).
CANDIDATE_RETRIEVERS: dict[str, CandidateRetriever] = {
    _catalog_retriever.name: _catalog_retriever,
    _audius_retriever.name: _audius_retriever,
}


def get_vibe_understander() -> VibeUnderstander:
    return _vibe_understander


def get_session_candidate_retriever() -> CandidateRetriever:
    return _catalog_retriever


def get_mix_candidate_retriever() -> CandidateRetriever:
    return _audius_retriever


def get_catalog_candidate_retriever() -> CandidateRetriever:
    """Direct access to the catalog retriever, used as mixes' safety-net
    fallback when the primary (Audius) retriever comes back empty."""

    return _catalog_retriever


def get_segment_selector() -> SegmentSelector:
    return _segment_selector


def get_transition_planner() -> TransitionPlanner:
    return _transition_planner


def get_audio_renderer() -> AudioRenderer:
    return _audio_renderer
