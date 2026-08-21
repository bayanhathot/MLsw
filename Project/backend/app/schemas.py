"""Validated API contracts for the Cuemix backend.

The project is intentionally keeping a single schema module for now.  The
contracts are grouped by domain and all user supplied strings are stripped at
the API boundary so whitespace-only prompts, feedback, posts, and messages
never reach the service layer.
"""

from datetime import datetime
from enum import StrEnum
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


class AutoMixMode(StrEnum):
    """The four literal auto-mix modes promised by the project proposal."""

    WORKOUT = "workout"
    RELAXATION = "relaxation"
    EMOTIONAL_TARAB = "emotional_tarab"
    PARTY = "party"


class StartSessionRequest(NonBlankModel):
    prompt: str = Field(min_length=1, max_length=300)
    mode: AutoMixMode | None = None


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
    mode: AutoMixMode | None = None
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


class PrepareNextRead(BaseModel):
    # True if session.prepared_next_json holds a valid entry once this call
    # returns, regardless of whether *this* call was the one that populated
    # it (a no-op because one was already prepared still reports True).
    prepared: bool
    # The prepared item's rendered audio URL, for the frontend's optional
    # preload step (PHASE_C_PREFETCH_DESIGN.md section 4.3) -- None whenever
    # `prepared` is False.
    audioUrl: str | None = None


class StartMixRequest(NonBlankModel):
    prompt: str = Field(min_length=1, max_length=300)
    mode: AutoMixMode | None = None


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
    track_duration_seconds: int | None = None
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
    mode: AutoMixMode | None = None
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


class PromptShortcutRead(BaseModel):
    prompt: str
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
    parent_comment_id: int | None = None


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
    parent_comment_id: int | None = None


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
        cleaned = list(
            dict.fromkeys(item.strip().lower() for item in value if item.strip())
        )
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
    client_event_id: str = Field(
        min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
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


class MostReplayedSegmentRead(BaseModel):
    segment_id: int | None = None
    title: str
    artist: str
    start_second: int
    end_second: int
    play_count: int
    replay_count: int
    seconds_listened: int


class SegmentAnalyticsRead(BaseModel):
    most_replayed_segment: MostReplayedSegmentRead | None = None
    average_segment_length_seconds: float | None = None
    time_saved_seconds: int = 0
    segment_play_count: int = 0
    time_saved_play_count: int = 0


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
    segment_analytics: SegmentAnalyticsRead
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


# Every status a job in the shared upload_queue.UploadQueue can be in --
# generic attachments (routers/uploads.py) and catalog tracks
# (routers/catalog.py) are jobs on the *same* queue/state machine, so they
# share this one status type rather than each declaring their own subset.
UploadJobStatus = Literal[
    "queued", "validating", "storing", "analyzing", "completed", "failed", "cancelled"
]


class UploadJobRead(BaseModel):
    job_id: str
    status: UploadJobStatus
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
    # Mirrors catalog_track_id's own role, one level removed: set by
    # pipeline.external_track_cache.enrich_and_dispatch when this Audius
    # candidate has a known external_tracks row (any analysis_status --
    # SegmentSelector itself decides whether to trust it, the same way it
    # already gates on CatalogTrack.analysis_status). None for a catalog
    # track, or an Audius track never yet seen/cached. The two are mutually
    # exclusive in practice (a Track is never both a catalog upload and an
    # Audius candidate), but nothing enforces that at the type level, same
    # as catalog_track_id/local_path's own relationship.
    external_track_id: int | None = None
    local_path: str | None = None


class SelectedSegment(BaseModel):
    track: Track
    start_second: int = Field(ge=0)
    end_second: int = Field(ge=0)
    method: Literal["chorus_detection", "whole_clip"]
    bpm: float | None = None
    # A genuine confidence signal for `bpm` (see
    # CatalogTrack.bpm_confidence/audio_analysis._bpm_confidence), not just
    # bpm itself -- transition_planner.py uses it to decide whether the
    # derived beat/phrase grid is trustworthy enough to gate a transition
    # on, since a shaky tempo estimate makes everything downstream of it
    # (the beat grid, and so downbeat_grid/phrase_boundaries) shakier too.
    bpm_confidence: float | None = None
    musical_key: str | None = None
    # "major"/"minor" (see CatalogTrack.key_mode) and the deterministic
    # Camelot-wheel code derived from (musical_key, key_mode) (see
    # CatalogTrack.camelot/audio_analysis.camelot_for). None under the
    # same conditions musical_key is.
    key_mode: str | None = None
    camelot: str | None = None
    # The correlation margin behind musical_key/key_mode's pick (see
    # CatalogTrack.key_confidence/audio_analysis._estimate_key).
    # transition_planner.py skips its harmonic-key bonus/penalty entirely
    # when this is low -- a low-confidence key guess must not drive a
    # transition decision any more than a missing one does.
    key_confidence: float | None = None
    # Coarse, heuristic phrase-boundary timestamps (seconds, absolute
    # within the source track) -- see CatalogTrack.phrase_boundaries_json/
    # audio_analysis._beat_grids for exactly how heuristic (a fixed
    # 4/4-time, 8-bar-phrase assumption, not real meter/structure
    # detection). None for an Audius track or a not-yet-analyzed catalog
    # track, same as bpm/musical_key.
    phrase_boundaries: list[float] | None = None
    # ITU-R BS.1770 integrated loudness (LUFS) of the source track, measured
    # once at analysis time (see CatalogTrack.integrated_loudness_lufs).
    # None for an Audius track (no catalog analysis exists) or a catalog
    # track not yet analyzed -- audio_renderer.py skips loudness
    # normalization entirely in that case, the same None-means-skip
    # handling bpm/musical_key already get in transition_planner.py.
    integrated_loudness_lufs: float | None = None


class TransitionPlan(BaseModel):
    crossfade_ms: int = Field(ge=0)
    style: Literal["crossfade", "cut"]
    notes: str
    # Structured decision factors DeterministicTransitionPlanner.plan()
    # already computes internally but previously only folded into the free-
    # text `notes` string above -- surfaced as their own fields so the admin
    # debug dashboard (and any other caller) can read the actual comparison
    # results without parsing prose. None where the comparison didn't happen
    # at all (key_category/phrase_aligned are both None for the first-track
    # case -- see plan()'s own docstring).
    key_category: str | None = None
    phrase_aligned: bool | None = None
    # Whether max_crossfade_ms (the reserved-region ceiling, see plan()'s
    # docstring) actually reduced crossfade_ms below what tempo/key/smoother
    # scoring alone would have produced -- distinct from crossfade_ms==0,
    # which can also happen via the hard-cut/no-phrase-boundary path with no
    # cap involved at all.
    capped_by_reserved_window: bool = False


class RenderedAudio(BaseModel):
    audio_url: str
    offsets: list[tuple[int, int]]
    is_pass_through: bool = False
    # Short machine-readable cause when is_pass_through is True (e.g.
    # "download_failed_ConnectError", "decode_failed_CouldntDecodeError") --
    # surfaced in the pipeline debug trace so a pass-through is diagnosable
    # without grepping backend logs. None whenever is_pass_through is False.
    fallback_reason: str | None = None


class StagedRender(BaseModel):
    """One playable clip produced by AudioRenderer.render_track_transition/
    render_bridge (session_manager.py's live-crossfade reserved-region
    mechanism) -- a single rendered file plus its own duration, not a
    composite with per-input offsets like RenderedAudio (whose `offsets`
    field is mix-specific and meaningless for a single staged clip)."""

    audio_url: str
    duration_ms: int = Field(ge=0)
    is_pass_through: bool = False
    fallback_reason: str | None = None
    # SHA-256 of the complete remote bytes _load_clip fetched to build this
    # clip -- set only when a real remote download happened (never for a
    # local_path load, and never on failure). Lets
    # pipeline.external_track_cache.verify_fingerprint (Prompt 4) compare
    # against a cached external_tracks row's stored audio_sha256 using
    # bytes already fetched for playback, with no second network request
    # purely for hashing.
    audio_sha256: str | None = None


class StagedTrackRender(BaseModel):
    """A track's audio split at selection time into a body (played first,
    unchanged from today's single-segment playback) and a reserved tail
    (always played next, either blended into a real crossfade or verbatim
    -- see AudioRenderer.render_track_transition). `reserved_tail` is None
    only when `body.is_pass_through` is True -- a track whose audio
    couldn't be fetched at all never enters the reserved-window mechanism,
    it behaves exactly like today's single pass-through."""

    body: StagedRender
    reserved_tail: StagedRender | None = None


class BridgeRender(BaseModel):
    """The output of AudioRenderer.render_bridge: the previous track's
    reserved tail blended against a resolved next track's head (`bridge`),
    plus that next track's own body+tail, rendered in the same call since
    its audio was already loaded to build the blend -- no second fetch
    needed when the bridge finishes playing and the next track's body
    starts. `next_reserved_tail` is None under the same pass-through
    condition as StagedTrackRender.reserved_tail.

    `crossfade_ms` is the *actually used* blend length -- render_bridge
    clamps its caller-requested crossfade_ms defensively against both
    clips' real lengths before rendering, so this can be shorter than what
    was asked for. session_manager.py must use this value (not its own
    request) as `next_body`'s resume point: any mismatch between the two
    would either replay already-blended audio a second time or skip a gap
    of it at the seam between the bridge and next_body. 0 alongside a
    pass-through `bridge`/`next_body` (no real blend happened)."""

    bridge: StagedRender
    next_body: StagedRender
    next_reserved_tail: StagedRender | None = None
    crossfade_ms: int = Field(ge=0, default=0)


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
    # Whether session.prepared_next_json currently holds an unconsumed
    # prepare_next() result -- prepare_next() never touches `trace` above
    # (see PHASE_C_PREFETCH_DESIGN.md section 3.5), so without this the
    # panel would have no visibility into the prefetch side of the loop.
    has_prepared_next: bool = False


class OllamaLastCallRead(BaseModel):
    at: datetime | None = None
    latency_ms: float | None = None
    ok: bool | None = None
    outcome: (
        Literal[
            "success", "timeout", "http_error", "invalid_response", "unexpected_error"
        ]
        | None
    ) = None


class OllamaStatsRead(BaseModel):
    """Cumulative, per-process call counters -- see
    prompt_parser.get_ollama_stats's own docstring. Meaningful on its own
    when BACKEND_WORKERS is 1; with more replicas, see OllamaHealthRead.
    cluster_stats for the cross-replica aggregate (D6b)."""

    attempted: int
    succeeded: int
    timed_out: int
    http_errors: int
    invalid_responses: int
    unexpected_errors: int
    shed: int
    success_rate: float | None = None
    mean_latency_ms: float | None = None


class OllamaHealthRead(BaseModel):
    configured: bool
    reachable: bool
    error: str | None = None
    configured_model: str | None = None
    loaded_models: list[str] = Field(default_factory=list)
    last_call: OllamaLastCallRead
    stats: OllamaStatsRead
    # D6b: None whenever Redis isn't configured/reachable (see
    # prompt_parser.get_cluster_ollama_stats' own docstring) -- distinct
    # from a real all-zero cluster with no calls yet.
    cluster_stats: OllamaStatsRead | None = None


class PipelineDebugRead(BaseModel):
    ollama: OllamaHealthRead
    sessions: list[SessionPipelineDebugRead]


class ExternalTrackDebugRead(BaseModel):
    """Read-only view of one external_tracks row for the owner-only admin
    debug dashboard (routers/admin_debug.py) -- deliberately a curated
    subset, not every column: no audio_sha256 (an integrity fingerprint,
    not something this view's stated purpose -- finding/diagnosing a
    track -- needs), no beat_grid_json/downbeat_grid_json/
    phrase_boundaries_json (large arrays with no debugging value in a
    table row)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str
    title: str
    artist: str
    album: str | None = None
    analysis_status: Literal["pending", "completed", "failed", "not_applicable"]
    analysis_attempt_count: int
    analysis_last_failed_at: datetime | None = None
    analyzed_at: datetime | None = None
    is_stale: bool
    bpm: float | None = None
    musical_key: str | None = None
    camelot: str | None = None
    integrated_loudness_lufs: float | None = None
    segment_method: str | None = None
    last_seen_at: datetime
    last_verified_at: datetime | None = None
    created_at: datetime


class AdminDebugEventRead(BaseModel):
    """One entry from the admin debug dashboard's in-memory recent-activity
    ring buffer (services/admin_debug_events.py) -- the raw structured
    event dict every entry already is (session_stage_latency,
    prepare_next_latency, session_create_failed), passed through as-is
    rather than re-typed field by field, since new event `event` kinds can
    be added at their call site without a schema change here."""

    model_config = ConfigDict(extra="allow")

    event: str


class AdminDebugSessionsRead(BaseModel):
    sessions: list[SessionPipelineDebugRead]


class AdminDebugExternalTracksRead(BaseModel):
    tracks: list[ExternalTrackDebugRead]


class AdminDebugEventsRead(BaseModel):
    events: list[AdminDebugEventRead]


class CatalogTrackRead(BaseModel):
    id: int
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    lyrics: str | None = None
    visibility: Literal["private", "public"]
    duration_seconds: int
    analysis_status: Literal["pending", "completed", "failed", "not_applicable"]
    audio_url: str
    cover_url: str | None = None
    created_at: datetime


class CatalogUploadJobRead(BaseModel):
    """One file within a bulk catalog upload -- see routers/catalog.py's
    /catalog/tracks/batch-jobs and /catalog/tracks/batches/{batch_id}."""

    job_id: str
    batch_id: str
    filename: str
    status: UploadJobStatus
    priority: int
    track: CatalogTrackRead | None = None
    error: str | None = None


class CatalogBatchStatusRead(BaseModel):
    batch_id: str
    total: int
    queued: int
    validating: int
    storing: int
    analyzing: int
    completed: int
    failed: int
    cancelled: int
    jobs: list[CatalogUploadJobRead]
