"""Persistent AI-DJ session and feedback models."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.core.time import utc_now


class DJSession(Base):
    """Persists a live SessionState: the mutated Intent plus whichever
    CandidateRetriever/segment/transition it currently resolves to."""

    __tablename__ = "dj_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('playing', 'stopped')", name="ck_dj_session_status"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="playing")
    vibe_label: Mapped[str] = mapped_column(String(100), nullable=False)
    # Name of the CandidateRetriever bound for this session's lifetime, e.g.
    # "catalog" or "audius" -- feedback re-invokes this same one.
    retriever_name: Mapped[str] = mapped_column(String(40), nullable=False)
    # The current, feedback-mutated PromptIntent for this session.
    intent_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Serialized NowPlayingRead-shaped data for the current track/segment.
    now_playing_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Serialized ReasoningRead-shaped data (selectedMoment/transitionPlan/nextDirection).
    reasoning_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    selected_feedback: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    feedback_events: Mapped[list["SessionFeedback"]] = relationship(
        "SessionFeedback", cascade="all, delete-orphan", passive_deletes=True
    )


class SessionFeedback(Base):
    __tablename__ = "session_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("dj_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    feedback: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_feedback: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    feedback: Mapped[str] = mapped_column(String(40), primary_key=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )
