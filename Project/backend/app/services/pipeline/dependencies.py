"""FastAPI Depends() providers for the AI-DJ pipeline stages.

Swapping a stage's implementation later is a one-line change to the provider
function it's bound to here -- nothing that calls Depends(get_x) needs to
change. Sessions and mixes both primary-retrieve from Audius and fall back
to the local catalog only when Audius finds nothing (session_manager.py /
mix_service.py): the local catalog is a tiny seed/upload set, a poor primary
source for a generic vibe/genre request (most requests never name an
artist), so Audius -- which can actually answer what was asked -- goes
first for both surfaces. get_session_candidate_retriever() and
get_mix_candidate_retriever() happen to return the same Audius singleton
today; each is free to diverge to a different implementation later without
the other, or the caller, changing.
"""

import logging
import os

from app.services.pipeline.audio_renderer import PydubAudioRenderer
from app.services.pipeline.audius_retriever import AudiusCandidateRetriever, MultiQueryAudiusRetriever
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
from app.services.pipeline.vibe import DeterministicOnlyVibeUnderstander, OllamaVibeUnderstander

logger = logging.getLogger(__name__)


def _build_vibe_understander() -> VibeUnderstander:
    """Which LLM (if any) refines the deterministic parse is a runtime
    setting -- VIBE_LLM_PROVIDER -- not a class picked at import time, so the
    concrete implementation can be switched with no code change. Defaults to
    Ollama, the sole LLM option (fully local, no hosted-API dependency);
    "none" skips the LLM step entirely.
    """

    provider = os.getenv("VIBE_LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        # A missing/incomplete config here must not crash the whole app:
        # parse_prompt already fails open to the deterministic parse on
        # every call when OLLAMA_BASE_URL/OLLAMA_MODEL are unset or the
        # request fails/times out (same as Audius being unavailable), so the
        # optional LLM step degrading gracefully must not depend on
        # remembering to also set VIBE_LLM_PROVIDER=none, and must never
        # gate startup on the ollama container's health (see
        # docker-compose.prod.yml's backend service).
        if not os.getenv("OLLAMA_BASE_URL", "").strip() or not os.getenv("OLLAMA_MODEL", "").strip():
            logger.warning(
                "VIBE_LLM_PROVIDER=ollama but OLLAMA_BASE_URL/OLLAMA_MODEL "
                "are not fully set; prompt classification will use the "
                "deterministic parse only."
            )
        return OllamaVibeUnderstander()
    if provider == "none":
        return DeterministicOnlyVibeUnderstander()
    raise RuntimeError(
        f"Unknown VIBE_LLM_PROVIDER={provider!r}; expected 'ollama' or 'none'."
    )


def _build_audius_retriever() -> CandidateRetriever:
    """Which Audius retrieval strategy runs is a runtime setting --
    AUDIUS_RETRIEVER -- not a class picked at import time, mirroring
    VIBE_LLM_PROVIDER above. If the multi-query path (see
    VIBE_RECOMMENDATION_DESIGN.md) ever behaves worse in practice, it's a
    one-env-var rollback to the original single-query retriever, not a
    revert.
    """

    mode = os.getenv("AUDIUS_RETRIEVER", "multi_query").strip().lower()
    if mode == "multi_query":
        return MultiQueryAudiusRetriever()
    if mode == "single_query":
        return AudiusCandidateRetriever()
    raise RuntimeError(
        f"Unknown AUDIUS_RETRIEVER={mode!r}; expected 'multi_query' or 'single_query'."
    )


# Stateless singletons: every implementation only takes a `db: Session` per
# call, so one shared instance per process is enough.
_vibe_understander = _build_vibe_understander()
_catalog_retriever = CatalogTrackRetriever()
_audius_retriever = _build_audius_retriever()
_segment_selector = LibrosaSegmentSelector()
_transition_planner = DeterministicTransitionPlanner()
_audio_renderer = PydubAudioRenderer()


def get_vibe_understander() -> VibeUnderstander:
    return _vibe_understander


def get_session_candidate_retriever() -> CandidateRetriever:
    """Sessions' primary retriever. Audius, not the local catalog: a
    session most often names no artist at all (a generic vibe/genre
    request), and the local catalog is a handful of seed/upload rows, not a
    real answer to that -- see get_catalog_candidate_retriever() for the
    fallback this surface falls through to when Audius comes back empty."""

    return _audius_retriever


def get_mix_candidate_retriever() -> CandidateRetriever:
    return _audius_retriever


def get_catalog_candidate_retriever() -> CandidateRetriever:
    """Direct access to the catalog retriever, used as both sessions' and
    mixes' safety-net fallback when the primary (Audius) retriever comes
    back empty."""

    return _catalog_retriever


def get_segment_selector() -> SegmentSelector:
    return _segment_selector


def get_transition_planner() -> TransitionPlanner:
    return _transition_planner


def get_audio_renderer() -> AudioRenderer:
    return _audio_renderer
