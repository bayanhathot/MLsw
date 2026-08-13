"""The deterministic-parse-plus-optional-Ollama VibeUnderstander."""

from app.schemas import PromptIntent
from app.services.pipeline.interfaces import VibeUnderstander
from app.services.prompt_parser import parse_prompt


class DeterministicVibeUnderstander(VibeUnderstander):
    """Wraps prompt_parser.parse_prompt: deterministic keyword parsing that an
    optional, schema-constrained Ollama call may refine (see prompt_parser.py
    for exactly which fields the LLM is and isn't trusted to set)."""

    def understand(self, prompt: str) -> PromptIntent:
        return parse_prompt(prompt)
