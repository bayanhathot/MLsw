"""Personalized prompt shortcuts: a lightweight memory of how a logged-in
user actually phrases their own prompts.

Clustered by *intent signature* (mood + energy + vocals + genres + whether
an artist was required), not exact text -- "gym energy please" and "make it
energetic for the gym" both parse to the same PromptIntent shape via
prompt_parser.py, so they count as the same repeated request instead of
needing exact string matches. A signature only becomes a visible shortcut
once it's been used PROMPT_SHORTCUT_MIN_USES times, so a one-off prompt
never creates chip noise (PromptComposer.svelte merges these ahead of the
static PRESETS list -- see routers/profiles.py's GET /me/prompt-shortcuts).
"""

import os

from sqlalchemy.orm import Session

from app.database.models.session import PromptShortcut
from app.schemas import PromptIntent

# A prompt must be seen at least this many times under the same intent
# signature before it's promoted to a visible shortcut chip.
PROMPT_SHORTCUT_MIN_USES = int(os.getenv("PROMPT_SHORTCUT_MIN_USES", "3"))

# How many personalized shortcuts the API ever returns -- PromptComposer
# fills the rest of its visible slots from the static PRESETS list, so this
# only needs to cover "a few of the user's own," not a wall of chips.
MAX_PROMPT_SHORTCUTS = int(os.getenv("MAX_PROMPT_SHORTCUTS", "3"))


def signature_for(intent: PromptIntent) -> str:
    """A stable clustering key for `intent`. Genres are sorted (order never
    carries meaning here, same rationale as
    session_candidate_pool.fingerprint_for) and lowercased for the same
    reason mood/energy/vocals already are by PromptIntent's own literals.
    Only *whether* an artist was required is part of the signature, not
    which artist -- keying by the specific artist name would fragment "play
    <artist>" requests into one row per artist, a much finer grain than
    "how this user tends to use the app" needs."""

    genres = ",".join(sorted(genre.lower() for genre in intent.genres))
    artist_required = intent.artist_mode == "required"
    return f"{intent.mood.lower()}|{intent.energy}|{intent.vocals}|{genres}|{artist_required}"


def record_prompt(db: Session, user_id: int, prompt: str, intent: PromptIntent) -> None:
    """Upserts the (user, signature) row: increments its count and refreshes
    its stored prompt text to `prompt` (the most-recent phrasing wins as the
    chip's label/prompt text, so it stays current with how the user actually
    talks today). Does not commit -- same convention every other mutation in
    session_manager.py's resolution flow follows; the caller's own commit
    (create_session's) covers this too."""

    signature = signature_for(intent)
    row = db.get(PromptShortcut, (user_id, signature))
    if row is None:
        db.add(PromptShortcut(user_id=user_id, signature=signature, prompt=prompt, count=1))
        # Flushed (not committed -- the caller still owns that) so a second
        # record_prompt call for the same (user_id, signature) within the
        # same transaction sees this row via db.get() above instead of also
        # taking the insert branch and colliding on the primary key.
        db.flush()
        return
    row.count += 1
    row.prompt = prompt


def top_shortcuts(db: Session, user_id: int) -> list[PromptShortcut]:
    """Shortcuts that have earned visibility (count >= PROMPT_SHORTCUT_MIN_USES),
    ranked by frequency then recency, capped at MAX_PROMPT_SHORTCUTS."""

    return (
        db.query(PromptShortcut)
        .filter(
            PromptShortcut.user_id == user_id,
            PromptShortcut.count >= PROMPT_SHORTCUT_MIN_USES,
        )
        .order_by(PromptShortcut.count.desc(), PromptShortcut.updated_at.desc())
        .limit(MAX_PROMPT_SHORTCUTS)
        .all()
    )
