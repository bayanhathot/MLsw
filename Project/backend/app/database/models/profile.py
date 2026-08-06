"""
profile.py

This file defines the profiles table.

Profile is a separate, one-to-one table rather than new columns on
User - that keeps User (see user.py) purely about authentication, the
same separation of concerns auth_service.py already relies on. Being a
separate table also means adding it here was a pure additive change:
no ALTER on the users table, no migration conflict with earlier phases.

Every field is optional/has a default: a profile is lazily created the
first time it's read or edited (see services/profile_service.py), so
there is never a "no profile yet" error state to handle in the API.
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Profile(Base):
    """
    SQLAlchemy model for the profiles table.
    """

    __tablename__ = "profiles"

    __table_args__ = (
        CheckConstraint(
            "theme_preference IN ('dark', 'light', 'system')",
            name="ck_profiles_theme_valid",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(280), nullable=True)

    # Stored as a portable JSON list[str] rather than postgresql.ARRAY -
    # the test suite runs against SQLite in-memory, which has no ARRAY type.
    favorite_genres: Mapped[list | None] = mapped_column(JSON, nullable=True)

    theme_preference: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="dark",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        onupdate=datetime.utcnow,
    )
