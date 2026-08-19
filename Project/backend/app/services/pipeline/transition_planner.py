"""TransitionPlanner: deterministic crossfade rules driven by BPM/key/phrase.

Every branch here is plain arithmetic over known numbers (a tempo
difference, a Camelot-wheel distance, a phrase-boundary timestamp) -- there
is no scoring/weighting model, matching this pipeline's "no ranking stage"
design.

Key compatibility (see _key_category) is now real Camelot-wheel-aware
categorization (same key > relative major/minor > adjacent Camelot >
compatible fifth > conflicting), not bare pitch-class-circle distance --
worth noting the old bare-distance scheme this replaces had its
compatible/clashing thresholds backwards relative to real music theory: a
genuine fifth interval sits at pitch-class-circle distance 5, not 1, so the
old KEY_CLASHING_DISTANCE=5 was actually flagging real fifths as clashes.
Every harmonic-key bonus/penalty is skipped entirely -- treated as
unknown/neutral, never guessed -- whenever either side's key_confidence is
too low to trust (see _key_category's own docstring): Phase 1's
key_confidence was computed but never actually used in a decision before
this.

Phrase alignment (see _lands_near_a_phrase_boundary) is a HARD constraint,
not one more soft-weighted term: landing off-phrase is audible on nearly
every affected transition, unlike a slightly suboptimal energy match. When
trustworthy phrase_boundaries data exists for the outgoing segment (see
_trusted_phrase_boundaries for what "trustworthy" means here) and no
boundary falls within reach of where that segment actually ends, this
forces a hard cut (crossfade_ms=0) instead of ever presenting an
off-phrase blend as if it were precisely timed. When phrase data is
missing or not trustworthy, this constraint is skipped entirely and the
decision falls back to today's bpm/key-only behavior -- phrase_boundaries
is "best available, not ground truth" (audio_analysis.py's own
downbeat_grid/phrase_boundaries docstring), so a shaky guess must never
produce a *worse* transition than simply not having the data at all.
"""

from app.schemas import SelectedSegment, TransitionPlan
from app.services.pipeline.interfaces import TransitionPlanner

BASE_CROSSFADE_MS = 4000
MIN_CROSSFADE_MS = 1500
MAX_CROSSFADE_MS = 8000
SMOOTHER_BONUS_MS = 1500

TEMPO_CLOSE_BPM = 3.0
TEMPO_FAR_BPM = 15.0
TEMPO_COMPATIBLE_BONUS_MS = 1000
TEMPO_CLASHING_PENALTY_MS = 1250

# A genuine perfect-fifth interval (7 semitones, or equivalently -5) sits
# at shortest-path pitch-class-circle distance 5 -- see _key_distance.
_FIFTH_PITCH_CLASS_DISTANCE = 5

_KEY_CATEGORY_BONUS_MS = {
    "same_key": 2000,
    "relative": 1500,
    "adjacent_camelot": 1000,
    "compatible_fifth": 500,
    "conflicting": -2000,
}

# Below this, musical_key/key_mode's own correlation margin (see
# audio_analysis._estimate_key) is treated as too ambiguous to drive a
# transition decision -- the harmonic-key bonus/penalty is skipped
# entirely (key_category effectively "unknown") rather than trusting a
# guess. Tunable; correlation margins for real (non-textbook) audio are
# often modest, so this is deliberately not set high.
_MIN_KEY_CONFIDENCE_FOR_HARMONIC_BONUS = 0.15

# phrase_boundaries is only trusted as a hard constraint when *both* of
# these hold -- see _trusted_phrase_boundaries.
_MIN_PHRASE_BOUNDARIES_FOR_TRUST = 2
_MIN_BPM_CONFIDENCE_FOR_PHRASE_TRUST = 0.3

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _key_distance(a: str | None, b: str | None) -> int | None:
    """Shortest distance around the 12-pitch-class circle; None if unknown."""

    if not a or not b or a not in _PITCH_CLASSES or b not in _PITCH_CLASSES:
        return None
    index_a, index_b = _PITCH_CLASSES.index(a), _PITCH_CLASSES.index(b)
    diff = abs(index_a - index_b) % 12
    return min(diff, 12 - diff)


def _camelot_number_and_letter(code: str) -> tuple[str, str]:
    return code[:-1], code[-1]


def _camelot_number_distance(a: str, b: str) -> int:
    """Circular distance (0-6) between two Camelot wheel numbers, ignoring
    letter -- e.g. "8B"/"9A" -> distance 1."""

    number_a, _ = _camelot_number_and_letter(a)
    number_b, _ = _camelot_number_and_letter(b)
    diff = abs(int(number_a) - int(number_b)) % 12
    return min(diff, 12 - diff)


def _key_category(previous: SelectedSegment, next_segment: SelectedSegment) -> str | None:
    """Categorizes the harmonic relationship between two segments' detected
    keys into one of five tiers, most to least compatible:

    - "same_key": identical pitch class AND mode.
    - "relative": same Camelot number, opposite letter (the relative
      major/minor pair -- same notes, different tonal center). Requires
      both sides to have a stored camelot code.
    - "adjacent_camelot": Camelot numbers exactly one wheel-step apart,
      same letter -- the canonical "move to the neighboring wedge" DJ
      move (a perfect fifth, same mode). Requires both sides' camelot.
    - "compatible_fifth": a genuine fifth by *raw pitch class*
      (_key_distance == _FIFTH_PITCH_CLASS_DISTANCE), independent of
      camelot/mode -- the fallback tier when full camelot/mode data isn't
      available on both sides but the pitch classes alone still suggest a
      musically sensible fifth-based move.
    - "conflicting": none of the above -- includes, deliberately, a
      same-pitch-class-different-mode pair (e.g. C major -> C minor,
      "parallel" major/minor): bare pitch-class distance alone would call
      that a perfect match (distance 0), but it is neither the same key
      (mode differs) nor a relative pair (different Camelot number) --
      real key-aware categorization must not collapse it into "same_key"
      just because the naive distance is zero.

    Returns None -- no bonus/penalty applied at all, key_category treated
    as unknown -- whenever either side has no musical_key, or either
    side's key_confidence is below _MIN_KEY_CONFIDENCE_FOR_HARMONIC_BONUS.
    A low-confidence key guess must not drive a transition decision any
    more than a missing one does."""

    if previous.musical_key is None or next_segment.musical_key is None:
        return None
    if (
        previous.key_confidence is None
        or previous.key_confidence < _MIN_KEY_CONFIDENCE_FOR_HARMONIC_BONUS
        or next_segment.key_confidence is None
        or next_segment.key_confidence < _MIN_KEY_CONFIDENCE_FOR_HARMONIC_BONUS
    ):
        return None

    if previous.musical_key == next_segment.musical_key and previous.key_mode == next_segment.key_mode:
        return "same_key"

    if previous.camelot and next_segment.camelot:
        prev_number, prev_letter = _camelot_number_and_letter(previous.camelot)
        next_number, next_letter = _camelot_number_and_letter(next_segment.camelot)
        if prev_number == next_number and prev_letter != next_letter:
            return "relative"
        if prev_letter == next_letter and _camelot_number_distance(previous.camelot, next_segment.camelot) == 1:
            return "adjacent_camelot"

    if _key_distance(previous.musical_key, next_segment.musical_key) == _FIFTH_PITCH_CLASS_DISTANCE:
        return "compatible_fifth"

    return "conflicting"


def _trusted_phrase_boundaries(segment: SelectedSegment) -> list[float] | None:
    """Returns segment.phrase_boundaries only when there's enough behind it
    to actually gate a transition decision on -- None (meaning: skip the
    phrase hard constraint entirely, fall back to today's bpm/key-only
    behavior) otherwise. Two cheap, honest disqualifiers, either enough on
    its own:

    - Fewer than _MIN_PHRASE_BOUNDARIES_FOR_TRUST entries:
      audio_analysis._beat_grids' phrase_boundaries is a fixed-stride
      slice of downbeat_grid that always includes index 0 even when the
      track was far too short/sparse to ever observe a genuine repeat --
      a single boundary proves nothing about real periodic structure,
      just where the beat grid happened to start.
    - bpm_confidence below _MIN_BPM_CONFIDENCE_FOR_PHRASE_TRUST: the whole
      downbeat/phrase heuristic is built directly on beat_track's own
      beat grid (see audio_analysis.py's module docstring) -- a shaky
      tempo estimate makes the derived fixed-4/4 grouping even shakier,
      not more trustworthy."""

    if not segment.phrase_boundaries or len(segment.phrase_boundaries) < _MIN_PHRASE_BOUNDARIES_FOR_TRUST:
        return None
    if segment.bpm_confidence is None or segment.bpm_confidence < _MIN_BPM_CONFIDENCE_FOR_PHRASE_TRUST:
        return None
    return segment.phrase_boundaries


def _lands_near_a_phrase_boundary(previous: SelectedSegment, reach_ms: int) -> bool:
    """True if a trusted phrase boundary of `previous` falls within
    `reach_ms` of where its own selected segment actually ends -- i.e.
    somewhere within the audio a crossfade could physically blend. True
    (never gates) whenever `previous` has no trustworthy phrase data at
    all -- see _trusted_phrase_boundaries."""

    trusted = _trusted_phrase_boundaries(previous)
    if trusted is None:
        return True
    reach_seconds = reach_ms / 1000.0
    return any(
        previous.end_second - reach_seconds <= boundary <= previous.end_second
        for boundary in trusted
    )


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
        never let a session-only tuning knob affect mix rendering. The same
        value (or MAX_CROSSFADE_MS when not given, i.e. for mix_service.py)
        is also how far back _lands_near_a_phrase_boundary looks for a
        phrase boundary to align to -- the same "how much audio is
        actually reachable" reasoning applies to both."""

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
        tempo_compatible = tempo_diff is not None and tempo_diff <= TEMPO_CLOSE_BPM
        tempo_clashing = tempo_diff is not None and tempo_diff > TEMPO_FAR_BPM
        key_category = _key_category(previous, next_segment)

        crossfade_ms = BASE_CROSSFADE_MS
        notes_parts = []
        if tempo_compatible:
            crossfade_ms += TEMPO_COMPATIBLE_BONUS_MS
            notes_parts.append("matching tempo")
        elif tempo_clashing:
            crossfade_ms -= TEMPO_CLASHING_PENALTY_MS
            notes_parts.append("a tempo mismatch")
        else:
            notes_parts.append("partial or moderately different tempo")

        if key_category is not None:
            crossfade_ms += _KEY_CATEGORY_BONUS_MS[key_category]
            notes_parts.append(f"a {key_category.replace('_', ' ')} harmonic relationship")
        else:
            notes_parts.append("no trusted key data")
        notes = f"Crossfade shaped by {' and '.join(notes_parts)}."

        if prefers_smoother:
            crossfade_ms += SMOOTHER_BONUS_MS
            notes += " Extended further because the listener asked for smoother transitions."

        crossfade_ms = max(MIN_CROSSFADE_MS, min(MAX_CROSSFADE_MS, crossfade_ms))

        reach_ms = max_crossfade_ms if max_crossfade_ms is not None else MAX_CROSSFADE_MS
        if not _lands_near_a_phrase_boundary(previous, reach_ms):
            return TransitionPlan(
                crossfade_ms=0,
                style="cut",
                notes=(
                    "No phrase boundary within reach of this track's own selected "
                    "ending -- a hard cut avoids presenting an off-phrase blend as "
                    "precisely timed."
                ),
            )

        if max_crossfade_ms is not None:
            # Applied last, deliberately after the MIN_CROSSFADE_MS floor
            # above -- see this method's docstring.
            crossfade_ms = min(crossfade_ms, max_crossfade_ms)
        return TransitionPlan(crossfade_ms=crossfade_ms, style="crossfade", notes=notes)
