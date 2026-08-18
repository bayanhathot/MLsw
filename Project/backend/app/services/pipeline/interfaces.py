"""Interface definitions for the five AI-DJ pipeline stages.

Each stage is bound to a concrete implementation via FastAPI Depends() in
dependencies.py. Swapping an implementation later means changing what that
provider function returns -- nothing that depends on the interface changes.
"""

from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.schemas import (
    BridgeRender,
    PromptIntent,
    RenderedAudio,
    SelectedSegment,
    StagedRender,
    StagedTrackRender,
    Track,
    TransitionPlan,
)


class VibeUnderstander(ABC):
    """Turns a free-text prompt into a structured PromptIntent."""

    @abstractmethod
    def understand(self, prompt: str) -> PromptIntent:
        raise NotImplementedError


class CandidateRetriever(ABC):
    """Returns playable Track candidates for an Intent, in deterministic order.

    An empty list means "nothing matched closely enough" -- callers must
    report that plainly rather than substitute an unrelated candidate.
    """

    name: str

    @abstractmethod
    def retrieve(
        self,
        db: Session,
        intent: PromptIntent,
        *,
        limit: int = 5,
        recent_artists: frozenset[str] = frozenset(),
        viewer_id: int | None = None,
    ) -> list[Track]:
        """`recent_artists` is an optional hint for session-aware diversity --
        artists that recently played in this session, so a ranking-capable
        implementation can penalize repeating one. Defaults to empty, and an
        implementation that has no ranking stage (e.g. the local catalog) is
        free to just accept and ignore it.

        `viewer_id` is the session's owning user (None for a guest session)
        -- a retrieval-source-owned catalog (e.g. CatalogTrackRetriever)
        must only ever return tracks that are `visibility="public"` or owned
        by this viewer; a source with no ownership concept (e.g. Audius) is
        free to accept and ignore it, same as recent_artists."""

        raise NotImplementedError


class SegmentSelector(ABC):
    """Picks the playable start/end window within one Track."""

    @abstractmethod
    def select(self, db: Session, track: Track) -> SelectedSegment:
        raise NotImplementedError


class TransitionPlanner(ABC):
    """Derives a deterministic crossfade plan between two segments."""

    @abstractmethod
    def plan(
        self,
        previous: SelectedSegment | None,
        next_segment: SelectedSegment,
        *,
        prefers_smoother: bool = False,
        max_crossfade_ms: int | None = None,
    ) -> TransitionPlan:
        """`max_crossfade_ms` is an optional hard ceiling on the returned
        crossfade_ms -- see DeterministicTransitionPlanner.plan()'s
        docstring for why (session_manager.py's reserved-region live
        crossfade mechanism; a no-op for any caller that doesn't pass it,
        e.g. mix_service.py)."""

        raise NotImplementedError


class AudioRenderer(ABC):
    """Renders one or more selected segments (with transitions) into playable audio."""

    @abstractmethod
    def render(
        self, segments: list[SelectedSegment], transitions: list[TransitionPlan]
    ) -> RenderedAudio:
        raise NotImplementedError

    @abstractmethod
    def render_track_transition(
        self, segment: SelectedSegment, *, resume_offset_ms: int, reserved_ms: int
    ) -> StagedTrackRender:
        """Loads `segment`'s audio once and splits it into a body (played
        first, from `resume_offset_ms` into the clip up to `reserved_ms`
        short of its own end) and a reserved tail (`reserved_ms` long,
        always played next -- see session_manager.py's reserved-region
        mechanism for why this is decided now, before any transition is
        planned). `resume_offset_ms` is 0 for a fresh track, or the
        crossfade length of the bridge that led into it for a track
        resuming after its own head was already played as part of a
        bridge. On a load failure, returns a StagedTrackRender whose body
        is an honest pass-through (same contract render()'s single-segment
        path already uses) and whose reserved_tail is None -- a track that
        couldn't be fetched never enters the reserved-window mechanism."""

        raise NotImplementedError

    @abstractmethod
    def render_bridge(
        self,
        tail: StagedRender,
        next_segment: SelectedSegment,
        *,
        crossfade_ms: int,
        reserved_ms: int,
    ) -> BridgeRender:
        """Blends `tail` (an already-rendered reserved tail, `reserved_ms`
        long) against `next_segment`'s head into a bridge clip exactly
        `reserved_ms` long (a plain prefix of `reserved_ms - crossfade_ms`,
        then a true blended overlap of `crossfade_ms`) -- and, since
        `next_segment`'s audio is loaded to build that blend anyway, also
        renders its own body+tail in the same call (resume_offset_ms=
        crossfade_ms), so the next track's own playback needs no further
        fetch once the bridge finishes. On a failure to load
        `next_segment`'s audio, returns a BridgeRender whose `bridge` is a
        pass-through and whose `next_body`/`next_reserved_tail` reflect
        that same failure -- the caller (session_manager.py) treats this
        exactly like today's single-candidate render failure and falls
        through to the next ranked candidate. The returned
        `BridgeRender.crossfade_ms` is the actually-used blend length
        (`crossfade_ms`, defensively re-clamped against both clips' real
        lengths) -- session_manager.py must resume `next_body`'s own
        playback from exactly this value, not its own request, or audio
        gets replayed or skipped at the bridge/next_body seam."""

        raise NotImplementedError
