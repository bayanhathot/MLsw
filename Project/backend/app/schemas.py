"""Validated API contracts for the Zonix backend.

The project is intentionally keeping a single schema module for now.  The
contracts are grouped by domain and all user supplied strings are stripped at
the API boundary so whitespace-only prompts, feedback, posts, and messages
never reach the service layer.
"""

from datetime import datetime
from typing import Literal

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
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)
    is_anonymous: bool = False
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


class PostRead(BaseModel):
    id: int
    author_id: int | None
    author_username: str
    title: str
    body: str
    is_anonymous: bool
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
    search_query: str = Field(min_length=1, max_length=120)
