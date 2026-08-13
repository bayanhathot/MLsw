"""VibeUnderstander implementations: deterministic keyword parsing, optionally
refined by one schema-constrained LLM call. Which implementation runs is a
runtime choice (VIBE_LLM_PROVIDER), made once at startup in
pipeline/dependencies.py -- the deterministic parser underneath
(prompt_parser.deterministic_parse) is identical no matter which one is
active, and every implementation is bound by the same guardrails (see
prompt_parser._apply_guardrails): the LLM may refine mood/energy/vocals/
genres, but can never override search_query or out-rank a regex-extracted
artist, since those are what CandidateRetriever depends on.
"""

from app.schemas import PromptIntent
from app.services.pipeline.interfaces import VibeUnderstander
from app.services.prompt_parser import deterministic_parse, parse_prompt, parse_prompt_groq


class GroqVibeUnderstander(VibeUnderstander):
    """Deterministic keyword parsing that a schema-constrained Groq call may
    refine. The default VibeUnderstander: no local model to host, so it's the
    fastest path to a working deployment (see prompt_parser.parse_prompt_groq)."""

    def understand(self, prompt: str) -> PromptIntent:
        return parse_prompt_groq(prompt)


class OllamaVibeUnderstander(VibeUnderstander):
    """Deterministic keyword parsing that a schema-constrained Ollama call may
    refine. Fully local, no external API dependency -- for anyone who'd
    rather self-host the LLM step (see prompt_parser.parse_prompt)."""

    def understand(self, prompt: str) -> PromptIntent:
        return parse_prompt(prompt)


class DeterministicOnlyVibeUnderstander(VibeUnderstander):
    """The keyword parser alone -- no LLM call of any kind."""

    def understand(self, prompt: str) -> PromptIntent:
        return deterministic_parse(prompt)
