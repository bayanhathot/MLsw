"""SQLAlchemy model for one directional user follow relationship."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class UserFollow(Base):
    """Connect a follower to a creator whose mixes they want to see."""

    __tablename__ = "user_follows"

    __table_args__ = (
        UniqueConstraint(
            "follower_id",
            "following_id",
            name="uq_user_follow_relationship",
        ),
        CheckConstraint(
            "follower_id <> following_id",
            name="ck_user_cannot_follow_self",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    follower_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    following_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
