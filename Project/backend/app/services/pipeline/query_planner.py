"""Deterministic search-string construction for MultiQueryAudiusRetriever.

Turns an already-classified PromptIntent into an ordered list of Audius
search strings -- most specific first, the raw prompt last -- so the
retriever can try narrow queries before broadening. Pure function, no I/O:
every field read here was already produced (and guardrailed against
LLM-invented content) by prompt_parser.py, so this never forwards freeform
LLM text as a query beyond what _apply_guardrails already allowed through.
"""

from app.schemas import PromptIntent

# "medium" deliberately has no term -- too vague to search on usefully, so
# that case falls through to the raw sentence like today.
_ENERGY_QUERY_TERMS = {"high": "high energy", "low": "chill"}


def build_queries(intent: PromptIntent, *, max_queries: int = 5) -> list[str]:
    queries: list[str] = []

    def add(candidate: str | None) -> None:
        if not candidate:
            return
        candidate = candidate.strip()
        if candidate and candidate.lower() not in (existing.lower() for existing in queries):
            queries.append(candidate)

    if intent.artist:
        add(intent.artist)
    for genre in intent.genres:
        add(genre)
    if len(intent.genres) >= 2:
        add(" ".join(intent.genres[:2]))
    if intent.mood and intent.mood != "balanced":
        if intent.genres:
            # Skip the combo when mood already equals the genre it'd be
            # paired with (e.g. mood="lofi", genres=["lofi"]) -- "lofi lofi"
            # is a degenerate query, not a narrower one.
            if intent.mood.lower() != intent.genres[0].lower():
                add(f"{intent.mood} {intent.genres[0]}")
        else:
            add(intent.mood)
    if not intent.genres:
        # No genre to search on at all -- intent.energy is always populated
        # (unlike mood/genres, which can be empty/"balanced") and is
        # reliably extracted even by the pure deterministic parser, e.g.
        # "gym" -> energy="high" with no genre word present. A generic
        # energy term still beats searching Audius with the raw sentence.
        energy_term = _ENERGY_QUERY_TERMS.get(intent.energy)
        if energy_term:
            add(energy_term)
    add(intent.search_query)

    return queries[:max_queries]
