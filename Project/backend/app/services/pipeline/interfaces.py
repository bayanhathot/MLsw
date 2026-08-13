"""Interface definitions for the five AI-DJ pipeline stages.

Each stage is bound to a concrete implementation via FastAPI Depends() in
dependencies.py. Swapping an implementation later means changing what that
provider function returns -- nothing that depends on the interface changes.
"""

from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.schemas import PromptIntent, RenderedAudio, SelectedSegment, Track, TransitionPlan


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
    def retrieve(self, db: Session, intent: PromptIntent, *, limit: int = 5) -> list[Track]:
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
    ) -> TransitionPlan:
        raise NotImplementedError


class AudioRenderer(ABC):
    """Renders one or more selected segments (with transitions) into playable audio."""

    @abstractmethod
    def render(
        self, segments: list[SelectedSegment], transitions: list[TransitionPlan]
    ) -> RenderedAudio:
        raise NotImplementedError
