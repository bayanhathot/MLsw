"""TransitionPlanner: deterministic crossfade rules driven by BPM/key.

Every branch here is plain arithmetic over known numbers (a tempo
difference, a pitch-class distance) -- there is no scoring/weighting model,
matching this pipeline's "no ranking stage" design.
"""

from app.schemas import SelectedSegment, TransitionPlan
from app.services.pipeline.interfaces import TransitionPlanner

BASE_CROSSFADE_MS = 4000
MIN_CROSSFADE_MS = 1500
MAX_CROSSFADE_MS = 8000
COMPATIBLE_BONUS_MS = 2000
CLASHING_PENALTY_MS = 2500
SMOOTHER_BONUS_MS = 1500

TEMPO_CLOSE_BPM = 3.0
TEMPO_FAR_BPM = 15.0
KEY_COMPATIBLE_DISTANCE = 1
KEY_CLASHING_DISTANCE = 5

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _key_distance(a: str | None, b: str | None) -> int | None:
    """Shortest distance around the 12-pitch-class circle; None if unknown."""

    if not a or not b or a not in _PITCH_CLASSES or b not in _PITCH_CLASSES:
        return None
    index_a, index_b = _PITCH_CLASSES.index(a), _PITCH_CLASSES.index(b)
    diff = abs(index_a - index_b) % 12
    return min(diff, 12 - diff)


class DeterministicTransitionPlanner(TransitionPlanner):
    def plan(
        self,
        previous: SelectedSegment | None,
        next_segment: SelectedSegment,
        *,
        prefers_smoother: bool = False,
        max_crossfade_ms: int | None = None,
    ) -> TransitionPlan:
        """`max_crossfade_ms`, when given, is a hard ceiling applied *after*
        every other rule below (including the MIN_CROSSFADE_MS floor) --
        session_manager.py's live-crossfade rendering reserves a fixed-size
        window at the tail of each selected segment before a transition is
        even planned, and the render literally cannot blend more audio than
        that window holds. A short reserved window can therefore push
        crossfade_ms *below* MIN_CROSSFADE_MS -- that's intentional: a hard
        physical constraint (how much audio was actually reserved) always
        wins over an aesthetic floor. mix_service.py's calls never pass
        this (whole segments are already fully available when a mix
        renders, no reservation happens), so this is a no-op for it --
        never let a session-only tuning knob affect mix rendering."""

        if previous is None:
            first_crossfade_ms = BASE_CROSSFADE_MS if prefers_smoother else 0
            if max_crossfade_ms is not None:
                first_crossfade_ms = min(first_crossfade_ms, max_crossfade_ms)
            return TransitionPlan(
                crossfade_ms=first_crossfade_ms,
                style="crossfade" if (prefers_smoother and first_crossfade_ms > 0) else "cut",
                notes="First track in this session/mix; nothing to blend from yet.",
            )

        tempo_diff = (
            abs(previous.bpm - next_segment.bpm)
            if previous.bpm is not None and next_segment.bpm is not None
            else None
        )
        key_distance = _key_distance(previous.musical_key, next_segment.musical_key)
        tempo_compatible = tempo_diff is not None and tempo_diff <= TEMPO_CLOSE_BPM
        tempo_clashing = tempo_diff is not None and tempo_diff > TEMPO_FAR_BPM
        key_compatible = key_distance is not None and key_distance <= KEY_COMPATIBLE_DISTANCE
        key_clashing = key_distance is not None and key_distance >= KEY_CLASHING_DISTANCE

        crossfade_ms = BASE_CROSSFADE_MS
        if tempo_compatible and key_compatible:
            crossfade_ms += COMPATIBLE_BONUS_MS
            notes = "Matching tempo and a compatible key: a long, blended crossfade."
        elif tempo_clashing or key_clashing:
            crossfade_ms -= CLASHING_PENALTY_MS
            notes = "Tempo or key mismatch: a shorter, harder cut to avoid a muddy blend."
        else:
            notes = "Standard crossfade; tempo/key data is partial or moderately different."

        if prefers_smoother:
            crossfade_ms += SMOOTHER_BONUS_MS
            notes += " Extended further because the listener asked for smoother transitions."

        crossfade_ms = max(MIN_CROSSFADE_MS, min(MAX_CROSSFADE_MS, crossfade_ms))
        if max_crossfade_ms is not None:
            # Applied last, deliberately after the MIN_CROSSFADE_MS floor
            # above -- see this method's docstring.
            crossfade_ms = min(crossfade_ms, max_crossfade_ms)
        return TransitionPlan(crossfade_ms=crossfade_ms, style="crossfade", notes=notes)
