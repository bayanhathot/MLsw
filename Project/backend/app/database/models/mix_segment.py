from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class MixSegment(Base):
    __tablename__ = "mix_segments"

    __table_args__ = (
        UniqueConstraint(
            "mix_id",
            "position",
            name="uq_mix_segment_position",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    mix_id: Mapped[int] = mapped_column(
        ForeignKey("mixes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    artist: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    audio_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    cover_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    start_second: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_second: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    transition_to_next: Mapped[str] = mapped_column(
        String(50),
        default="crossfade",
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source_track_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    mix = relationship(
        "Mix",
        back_populates="segments",
    )