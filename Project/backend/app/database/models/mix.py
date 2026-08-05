"""
Database model for a generated Zonix mix.

A Mix represents one AI DJ mix created by a user.

Important idea:
The mix itself is not one final MP3 file.
Instead, the mix has metadata here, and its playable parts are stored
separately in the mix_segments table.

Example flow:
1. User enters a prompt.
2. Backend generates a mix from Audius segments.
3. A Mix row is created with status = "draft".
4. When the user clicks "Post Mix", status becomes "published".
5. Published mixes appear in the public feed.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Mix(Base):
    __tablename__ = "mixes"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    prompt: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cover_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    owner = relationship(
    "User",
    back_populates="mixes",
)

    segments = relationship(
        "MixSegment",
        back_populates="mix",
        cascade="all, delete-orphan",
        order_by="MixSegment.position",
    )
