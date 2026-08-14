"""Validated API contracts for the Zonix backend.

The project is intentionally keeping a single schema module for now.  The
contracts are grouped by domain and all user supplied strings are stripped at
the API boundary so whitespace-only prompts, feedback, posts, and messages
never reach the service layer.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    is_active: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class NonBlankModel(BaseModel):
    """Base class that strips all declared string fields."""

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value


class StartSessionRequest(NonBlankModel):
    prompt: str = Field(min_length=1, max_length=300)


class SessionFeedbackRequest(NonBlankModel):
    feedback: str = Field(min_length=1, max_length=100)


class NowPlayingRead(BaseModel):
    title: str
    artist: str
    album: str
    coverUrl: str
    vibeLabel: str
    role: str


class ReasoningRead(BaseModel):
    selectedMoment: str
    transitionPlan: str
    nextDirection: str


class SessionRead(BaseModel):
    id: str
    prompt: str
    status: Literal["playing", "stopped"]
    vibeLabel: str
    audioUrl: str
    nowPlaying: NowPlayingRead
    reasoning: ReasoningRead
    selectedFeedback: str | None = None


class StopSessionRead(BaseModel):
    session_id: str
    status: Literal["stopped"]
    message: str


class StartMixRequest(NonBlankModel):
    prompt: str = Field(min_length=1, max_length=300)


class MixSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    title: str
    artist: str
    audio_url: str
    cover_url: str | None = None
    start_second: int
    end_second: int
    transition_to_next: str
    source: str
    source_track_id: str
    genre: str | None = None
    vibe: str | None = None


class MixOwnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class MixRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    title: str
    prompt: str
    description: str | None = None
    cover_url: str | None = None
    status: str
    created_at: datetime
    published_at: datetime | None = None
    segments: list[MixSegmentRead]


class MixFeedItem(MixRead):
    owner: MixOwnerRead
    like_count: int
    is_liked: bool
    is_saved: bool


class MixLibraryRead(BaseModel):
    owned: list[MixRead]
    saved: list[MixRead]


class MixUpdate(NonBlankModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    cover_url: str | None = Field(default=None, max_length=1000)


class PreferenceRead(BaseModel):
    feedback: str
    score: int
    count: int


# Forum, messaging, and upload contracts are defined here so every endpoint
# shares the same validation policy.
AttachmentKind = Literal["image", "video", "audio"]


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: AttachmentKind
    filename: str
    content_type: str
    url: str
    size_bytes: int


class PostCreate(NonBlankModel):
    title: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=1, max_length=5000)
    is_anonymous: bool = False
    kind: Literal["discussion", "status", "mix_share"] = "discussion"
    visibility: Literal["public", "friends"] = "public"
    mix_id: int | None = Field(default=None, ge=1)
    attachment_ids: list[int] = Field(default_factory=list, max_length=8)


class CommentCreate(NonBlankModel):
    body: str = Field(min_length=1, max_length=2000)
    is_anonymous: bool = False
    attachment_ids: list[int] = Field(default_factory=list, max_length=4)


class VoteRequest(BaseModel):
    value: Literal[-1, 1]


class CommentRead(BaseModel):
    id: int
    author_id: int | None
    author_username: str
    body: str
    is_anonymous: bool
    can_delete: bool
    score: int
    my_vote: int
    attachments: list[AttachmentRead]
    created_at: datetime


class SharedMixRead(BaseModel):
    id: int
    title: str
    prompt: str
    cover_url: str | None = None
    owner_username: str
    segment_count: int


class PostRead(BaseModel):
    id: int
    author_id: int | None
    author_username: str
    title: str
    body: str
    is_anonymous: bool
    kind: Literal["discussion", "status", "mix_share"] = "discussion"
    visibility: Literal["public", "friends"] = "public"
    mix: SharedMixRead | None = None
    can_delete: bool
    score: int
    comment_count: int
    my_vote: int
    attachments: list[AttachmentRead]
    created_at: datetime


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    favorite_genres: list[str] | None = None
    theme_preference: Literal["dark", "light", "system"]


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=1000)
    bio: str | None = Field(default=None, max_length=280)
    favorite_genres: list[str] | None = Field(default=None, max_length=20)
    theme_preference: Literal["dark", "light", "system"] | None = None

    @field_validator("display_name", "avatar_url", "bio")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("favorite_genres")
    @classmethod
    def normalize_genres(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))
        if len(cleaned) != len(value):
            raise ValueError("Genres must be nonblank and unique.")
        if any(len(item) > 40 for item in cleaned):
            raise ValueError("Genres must be at most 40 characters.")
        return cleaned


class ProfileStatsRead(BaseModel):
    received_upvotes: int
    received_downvotes: int
    post_count: int
    comment_count: int


class ListeningEventCreate(NonBlankModel):
    client_event_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    session_id: str | None = Field(default=None, max_length=48)
    mix_id: int | None = Field(default=None, ge=1)
    segment_id: int | None = Field(default=None, ge=1)
    started_at: datetime
    ended_at: datetime | None = None
    seconds_listened: int = Field(ge=0, le=86_400)
    skipped: bool = False


class ListeningEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_event_id: str
    session_id: str | None = None
    mix_id: int | None = None
    segment_id: int | None = None
    source: str
    source_track_id: str
    track_title: str
    artist_name: str
    genre: str | None = None
    vibe: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    seconds_listened: int
    track_duration_seconds: int | None = None
    segment_start_second: int | None = None
    segment_end_second: int | None = None
    completion_ratio: float | None = None
    skipped: bool
    created_at: datetime


class MusicMetricRead(BaseModel):
    name: str
    seconds: int
    percentage: float


class ListeningTrendPointRead(BaseModel):
    date: str
    seconds: int


class RecentListeningRead(BaseModel):
    key: str
    kind: Literal["mix", "session"]
    title: str
    subtitle: str | None = None
    seconds: int
    started_at: datetime


class ListeningDNADimensionRead(BaseModel):
    name: str
    value: float


class ListeningDNARead(BaseModel):
    status: str
    label: str | None = None
    summary: str | None = None
    dimensions: list[ListeningDNADimensionRead] = Field(default_factory=list)
    version: str | None = None


class TrackMetricRead(BaseModel):
    title: str
    artist: str
    seconds: int
    percentage: float


class MusicIdentitySummaryRead(BaseModel):
    total_listening_seconds: int
    top_artist: MusicMetricRead | None = None
    top_genre: MusicMetricRead | None = None
    top_vibe: MusicMetricRead | None = None
    artists_discovered: int = 0
    tracks_discovered: int = 0
    listening_contexts: int = 0
    average_context_seconds: int = 0


class MusicIdentityRead(BaseModel):
    is_public: bool
    visibility: Literal["private", "friends", "public"] = "private"
    period: Literal["7d", "30d", "6m", "all"] = "all"
    summary: MusicIdentitySummaryRead
    artists: list[MusicMetricRead]
    genres: list[MusicMetricRead]
    vibes: list[MusicMetricRead]
    top_tracks: list[TrackMetricRead] = Field(default_factory=list)
    time_of_day: list[MusicMetricRead] = Field(default_factory=list)
    listening_trend: list[ListeningTrendPointRead]
    recent_listening: list[RecentListeningRead]
    listening_dna: ListeningDNARead


class MusicIdentityPrivacyUpdate(BaseModel):
    is_public: bool | None = None
    visibility: Literal["private", "friends", "public"] | None = None


class PublicProfileRead(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    favorite_genres: list[str] | None = None
    member_since: datetime
    stats: ProfileStatsRead
    music_identity_public: bool
    music_identity_visibility: Literal["private", "friends", "public"] = "private"
    friend_count: int = 0
    mutual_friend_count: int = 0
    published_mix_count: int = 0
    relationship_status: str = "guest"
    viewer_has_blocked: bool = False


class PublicMusicIdentityRead(BaseModel):
    username: str
    is_public: bool
    music_identity: MusicIdentityRead | None = None


class UserCardRead(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    music_interests: list[str] | None = None
    friend_count: int = 0
    mutual_friend_count: int = 0
    relationship_status: str


class FriendRequestRead(BaseModel):
    id: int
    sender_username: str
    receiver_username: str
    status: str
    created_at: datetime
    responded_at: datetime | None = None
    other_user: UserCardRead | None = None


class ReportCreate(NonBlankModel):
    target_type: Literal["user", "post", "comment"]
    target_id: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=80)
    details: str | None = Field(default=None, max_length=1000)


class MessageCreate(NonBlankModel):
    recipient_username: str = Field(min_length=3, max_length=50)
    body: str = Field(min_length=1, max_length=4000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=4)


class MessageRead(BaseModel):
    id: int
    sender_id: int
    sender_username: str
    recipient_id: int
    recipient_username: str
    body: str
    attachments: list[AttachmentRead]
    created_at: datetime
    read_at: datetime | None = None


class ConversationRead(BaseModel):
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    last_message: str
    last_message_at: datetime
    unread_count: int



class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None
    is_read: bool
    created_at: datetime


class UploadBatchItem(NonBlankModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1, max_length=70_000_000)
    priority: int = Field(default=5, ge=0, le=10)


class UploadBatchRequest(BaseModel):
    files: list[UploadBatchItem] = Field(min_length=1, max_length=20)


class UploadJobRead(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    priority: int
    attachment: AttachmentRead | None = None
    error: str | None = None


class PromptIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mood: str = Field(min_length=1, max_length=40)
    energy: Literal["low", "medium", "high"]
    vocals: Literal["less", "neutral", "more"]
    genres: list[str] = Field(max_length=5)
    artist: str | None = Field(default=None, max_length=120)
    artist_mode: Literal["required", "reference", "none"] = "none"
    search_query: str = Field(min_length=1, max_length=120)


# ---------------------------------------------------------------------------
# AI-DJ pipeline contracts: VibeUnderstander -> CandidateRetriever ->
# SegmentSelector -> TransitionPlanner -> AudioRenderer.
#
# These are internal service-layer data shapes (not all are returned directly
# from an endpoint), kept in this module per its "single schema module"
# convention. `Track.local_path` is a server-side filesystem path and must
# never be included when building a public API response model.
# ---------------------------------------------------------------------------


class Track(BaseModel):
    source: Literal["catalog", "audius"]
    source_track_id: str
    title: str
    artist: str
    album: str | None = None
    audio_url: str
    cover_url: str | None = None
    duration_seconds: int = Field(ge=0)
    genre: str | None = None
    vibe: str | None = None
    vibe_label: str | None = None
    tags: str | None = None
    catalog_track_id: int | None = None
    local_path: str | None = None


class SelectedSegment(BaseModel):
    track: Track
    start_second: int = Field(ge=0)
    end_second: int = Field(ge=0)
    method: Literal["chorus_detection", "whole_clip"]
    bpm: float | None = None
    musical_key: str | None = None


class TransitionPlan(BaseModel):
    crossfade_ms: int = Field(ge=0)
    style: Literal["crossfade", "cut"]
    notes: str


class RenderedAudio(BaseModel):
    audio_url: str
    offsets: list[tuple[int, int]]
    is_pass_through: bool = False


# ---------------------------------------------------------------------------
# Internal pipeline/Ollama debug panel (routers/debug.py). Observability
# only -- read-only reflections of state the pipeline/session layer already
# produces, never accepted as input.
# ---------------------------------------------------------------------------


class SessionPipelineDebugRead(BaseModel):
    session_id: str
    prompt: str
    status: Literal["playing", "stopped"]
    user_id: int | None
    retriever_name: str
    vibe_label: str
    updated_at: datetime
    # Per-stage {implementation, ...short result} trace built in
    # session_manager._resolve_and_render; None for sessions created before
    # this column existed.
    trace: dict[str, Any] | None = None


class OllamaLastCallRead(BaseModel):
    at: datetime | None = None
    latency_ms: float | None = None
    ok: bool | None = None


class OllamaHealthRead(BaseModel):
    configured: bool
    reachable: bool
    error: str | None = None
    configured_model: str | None = None
    loaded_models: list[str] = Field(default_factory=list)
    last_call: OllamaLastCallRead


class PipelineDebugRead(BaseModel):
    ollama: OllamaHealthRead
    sessions: list[SessionPipelineDebugRead]


class CatalogTrackRead(BaseModel):
    id: int
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    duration_seconds: int
    analysis_status: Literal["pending", "completed", "failed", "not_applicable"]
    audio_url: str
    created_at: datetime
