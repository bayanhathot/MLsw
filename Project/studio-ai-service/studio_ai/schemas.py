from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class DiscoveryTrack(BaseModel):
    """Mirrors app/schemas.py::DiscoveryTrack exactly -- see that module's
    own docstring. The model may only echo a track already present in
    context["discovery_results"] back onto Recommendation.discovery_results
    (same source_type/source_track_id), with its own one-line `reason`;
    never invent one."""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["catalog", "audius"]
    source_track_id: str
    title: str
    artist: str
    duration_ms: int = Field(gt=0)
    bpm: float | None = None
    musical_key: str | None = None
    camelot: str | None = None
    vibe: str | None = None
    genre: str | None = None
    reason: str | None = Field(default=None, max_length=200)


class AddItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["catalog", "audius", "saved_segment"]
    source_track_id: str | None = Field(default=None, min_length=1, max_length=255)
    saved_segment_id: int | None = Field(default=None, ge=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)
    insert_after_item_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_type == "saved_segment":
            if self.saved_segment_id is None or self.source_track_id is not None:
                raise ValueError("saved_segment source requires only saved_segment_id.")
        else:
            if self.source_track_id is None or self.saved_segment_id is not None:
                raise ValueError("catalog/audius source requires only source_track_id.")
            if self.start_ms is None or self.end_ms is None:
                raise ValueError("A new segment requires start_ms and end_ms.")
            if self.end_ms <= self.start_ms:
                raise ValueError("end_ms must be greater than start_ms.")
        return self


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_type: Literal["explanation", "clarification", "plan", "refusal"]
    base_revision: int | None = Field(default=None, ge=1)
    remembered_constraints: list[str] = Field(default_factory=list, max_length=8)
    proposed_order: list[int] | None = Field(default=None, min_length=1, max_length=30)
    transition_changes: list[TransitionChange] = Field(default_factory=list, max_length=5)
    segment_bound_change: SegmentBoundChange | None = None
    removed_item_ids: list[int] = Field(default_factory=list, max_length=5)
    add_item: AddItem | None = None
    discovery_results: list[DiscoveryTrack] = Field(default_factory=list, max_length=10)
    suggested_action: (
        Literal["preview_transition", "preview_segment", "render_mix"] | None
    ) = None
    action_target_item_id: int | None = Field(default=None, ge=1)
    calculations: PlanCalculations | None = None
    warnings: list[str] = Field(default_factory=list, max_length=8)
    reason_tags: list[str] = Field(default_factory=list, max_length=8)
    explanation: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    requires_user_confirmation: bool = True

    @model_validator(mode="after")
    def validate_refusal_is_inert(self):
        if self.recommendation_type == "refusal" and (
            self.proposed_order is not None
            or self.transition_changes
            or self.segment_bound_change is not None
            or self.removed_item_ids
            or self.add_item is not None
            or self.discovery_results
            or self.suggested_action is not None
        ):
            raise ValueError("A refusal may not include any proposed change or action.")
        return self
