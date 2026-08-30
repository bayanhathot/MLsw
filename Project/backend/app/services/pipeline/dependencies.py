"""FastAPI Depends() providers for the AI-DJ pipeline stages.

Swapping a stage's implementation later is a one-line change to the provider
function it's bound to here -- nothing that calls Depends(get_x) needs to
change. Sessions and mixes both primary-retrieve from the local catalog and
fall back to Audius only when the catalog finds nothing or its own top match
is too weak to trust (see orchestrator.retrieve_candidates_with_fallback /
catalog_retriever.CATALOG_MATCH_THRESHOLD): the local catalog is now meant
to be the primary, full DJ source -- real per-track BPM/key/segment data
only exists for catalog tracks, never Audius ones -- with Audius as the
breadth-of-catalog safety net for whatever the local catalog doesn't have a
good answer for yet (ai-dj-segment-metadata-architecture.md §12).
get_session_candidate_retriever() and get_mix_candidate_retriever() happen
to return the same catalog singleton today; each is free to diverge to a
different implementation later without the other, or the caller, changing.

**The trade-off this wiring makes, explicitly:** catalog-primary gives up
some of Audius's breadth -- effectively unconstrained, any song, any artist
-- in exchange for the DJ actually being able to reason about what it's
playing (real BPM/key/segment data, not the "standard crossfade, partial
tempo/key data" default every Audius track hits). That trade only pays off
once the catalog has enough real, well-tagged uploads to cover a meaningful
slice of requests; Audius-as-fallback is what keeps sessions/mixes usable
in the meantime, while catalog volume grows.

CATALOG_MATCH_THRESHOLD (catalog_retriever.py) is the dial that trade-off
turns on, and it's genuinely two-sided, not just "tune it higher for
quality": set it too high and the catalog's own matches rarely clear the
bar, so the system is Audius-primary in practice regardless of what
dependencies.py wires -- the intelligence trade-off above never actually
gets cashed in. Set it too low (or route a bare mood_bucket match around
is_strong_catalog_match's genre-or-artist requirement) and it reintroduces
the exact bug the historical Audius-primary swap fixed and Prompt 7/8 spent
their effort guarding against: a thin catalog match looking like a
confident one and silently starving Audius of requests it should have
gotten. There's no static value that's simply "correct" here -- it needs
tuning against real usage, not theory (same "don't over-tune from theory
alone" stance ARTIST_MATCH_THRESHOLD already takes).
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
from app.services.pipeline.segment_selector import (
    FullTrackSegmentSelector,
    LibrosaSegmentSelector,
)
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
_full_track_segment_selector = FullTrackSegmentSelector()
_transition_planner = DeterministicTransitionPlanner()
_audio_renderer = PydubAudioRenderer()


def get_vibe_understander() -> VibeUnderstander:
    return _vibe_understander


def get_session_candidate_retriever() -> CandidateRetriever:
    """Sessions' primary retriever: the local catalog -- see
    get_audius_candidate_retriever() for the fallback this surface falls
    through to when the catalog comes back empty or too weak to trust
    (retrieve_candidates_with_fallback / CATALOG_MATCH_THRESHOLD)."""

    return _catalog_retriever


def get_mix_candidate_retriever() -> CandidateRetriever:
    return _catalog_retriever


def get_audius_candidate_retriever() -> CandidateRetriever:
    """Direct access to the Audius retriever, used as both sessions' and
    mixes' fallback when the primary (local catalog) retriever comes back
    empty or weak."""

    return _audius_retriever


def get_segment_selector() -> SegmentSelector:
    return _segment_selector


def get_full_track_segment_selector() -> SegmentSelector:
    """The 'full_songs' mix-scope alternative to get_segment_selector() --
    see FullTrackSegmentSelector's own docstring. Session routes inject
    both and pick whichever the session's own (or, at creation, the
    request's own) mix_scope calls for."""

    return _full_track_segment_selector


def get_transition_planner() -> TransitionPlanner:
    return _transition_planner


def get_audio_renderer() -> AudioRenderer:
    return _audio_renderer
