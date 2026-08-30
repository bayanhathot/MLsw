"""Persisted generated mixes and their ordered segments."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.database.base import Base


class Mix(Base):
    __tablename__ = "mixes"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="ck_mix_status"),
        CheckConstraint(
            "mode IS NULL OR mode IN ('workout', 'relaxation', 'emotional_tarab', 'party')",
            name="ck_mix_mode",
        ),
        CheckConstraint(
            "render_status IN ('not_rendered', 'rendering', 'ready', 'stale', 'failed')",
            name="ck_mix_render_status",
        ),
        CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_mix_visibility"
        ),
        CheckConstraint(
            "publication_mode IS NULL OR publication_mode IN ('rendered_asset', 'provider_manifest')",
            name="ck_mix_publication_mode",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(48), unique=True, nullable=False, index=True
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    # The literal proposal mode used to generate this persisted mix. Null is
    # the existing custom/free-prompt path and keeps older rows compatible.
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_studio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rendered_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_rendered"
    )
    rendered_audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_segments_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 'rendered_asset' (a durable, CueMix-hosted composite the client plays
    # directly) or 'provider_manifest' (an immutable playback recipe the
    # client reconstructs from live provider streams -- see
    # publish_service.py's own module docstring for the full rationale).
    # Nullable so a pre-existing published row from before this column
    # existed still validates; publish_service backfills/derives it lazily
    # wherever it matters instead of requiring every legacy row rewritten.
    publication_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The immutable public snapshot for a 'provider_manifest' publish (schema
    # per publish_service.MANIFEST_SCHEMA_VERSION) -- ordered segments with
    # provider identity, attribution, exact bounds/transitions, and the
    # rights/availability status recorded at publish time. None for a
    # 'rendered_asset' publish (published_audio_url is the whole story
    # there) and for any legacy row published before this existed; the
    # public playback-manifest endpoint reconstructs an equivalent manifest
    # on demand from published_segments_json for that legacy case rather
    # than ever depending on it being present.
    published_manifest_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner = relationship("User", back_populates="mixes")
    segments: Mapped[list["MixSegment"]] = relationship(
        "MixSegment",
        back_populates="mix",
        order_by="MixSegment.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MixSegment(Base):
    __tablename__ = "mix_segments"
    __table_args__ = (
        UniqueConstraint("mix_id", "position", name="uq_mix_segment_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mix_id: Mapped[int] = mapped_column(
        ForeignKey("mixes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    saved_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_segments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_second: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_second: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_to_next: Mapped[str] = mapped_column(
        String(50), nullable=False, default="crossfade"
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_track_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Studio keeps the exact source selection separate from the rendered
    # composite offsets in start_second/end_second. Generated mixes leave
    # these nullable and retain their historical contract unchanged.
    source_audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Full source-track duration, distinct from start/end which are offsets
    # into the rendered mix. Used by listening analytics to measure how much
    # time a selected moment saved versus playing its complete source track.
    track_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vibe: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    key_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    camelot: Mapped[str | None] = mapped_column(String(4), nullable=True)
    transition_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="crossfade"
    )
    transition_duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4000
    )
    compatibility_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compatibility_factors_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    mix = relationship("Mix", back_populates="segments")
