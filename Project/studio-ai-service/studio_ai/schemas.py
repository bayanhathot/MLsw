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


class SegmentBoundChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: int = Field(ge=1)
    proposed_start_ms: int = Field(ge=0)
    proposed_end_ms: int = Field(gt=0)


class PlanCalculations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_duration_ms: int = Field(ge=0)
    proposed_duration_ms: int = Field(ge=0)
    transition_overlap_ms: int = Field(ge=0)
    average_bpm_jump: float | None = Field(default=None, ge=0)
    known_bpm_pairs: int = Field(default=0, ge=0)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_type: Literal["explanation", "clarification", "plan"]
    base_revision: int | None = Field(default=None, ge=1)
    remembered_constraints: list[str] = Field(default_factory=list, max_length=8)
    proposed_order: list[int] | None = Field(default=None, min_length=1, max_length=30)
    transition_changes: list[TransitionChange] = Field(default_factory=list, max_length=5)
    segment_bound_change: SegmentBoundChange | None = None
    calculations: PlanCalculations | None = None
    warnings: list[str] = Field(default_factory=list, max_length=8)
    reason_tags: list[str] = Field(default_factory=list, max_length=8)
    explanation: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    requires_user_confirmation: bool = True
