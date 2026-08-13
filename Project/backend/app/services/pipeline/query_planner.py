"""Deterministic search-string construction for MultiQueryAudiusRetriever.

Turns an already-classified PromptIntent into an ordered list of Audius
search strings -- most specific first, the raw prompt last -- so the
retriever can try narrow queries before broadening. Pure function, no I/O:
every field read here was already produced (and guardrailed against
LLM-invented content) by prompt_parser.py, so this never forwards freeform
LLM text as a query beyond what _apply_guardrails already allowed through.
"""

from app.schemas import PromptIntent


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
    add(intent.search_query)

    return queries[:max_queries]
