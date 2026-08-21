from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(min_length=1, max_length=12)
    context: dict


class TransitionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(ge=1)
    transition_type: Literal["cut", "crossfade", "fade_in_out"]
    duration_ms: int = Field(ge=0, le=8000)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_type: Literal[
        "segment_bounds", "mix_order", "transition", "explanation"
    ]
    candidate_id: int | None = None
    proposed_start_ms: int | None = Field(default=None, ge=0)
    proposed_end_ms: int | None = Field(default=None, gt=0)
    proposed_order: list[int] | None = None
    transition_change: TransitionChange | None = None
    reason_tags: list[str] = Field(default_factory=list, max_length=8)
    explanation: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    requires_user_confirmation: bool = True
