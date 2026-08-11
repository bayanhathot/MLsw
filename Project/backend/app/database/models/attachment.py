"""Validated media metadata; an attachment belongs to at most one entity."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.core.time import utc_now


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("kind IN ('image', 'video', 'audio')", name="ck_attachment_kind"),
        CheckConstraint("size_bytes > 0", name="ck_attachment_nonempty"),
        CheckConstraint(
            "(CASE WHEN post_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN comment_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN message_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="ck_attachment_single_parent",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=True, index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("forum_comments.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("direct_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
