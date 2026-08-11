"""One-to-one public profile preferences."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.core.time import utc_now


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("theme_preference IN ('dark', 'light', 'system')", name="ck_profile_theme"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(280), nullable=True)
    favorite_genres: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    theme_preference: Mapped[str] = mapped_column(String(20), nullable=False, default="dark")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=utc_now, nullable=True)
