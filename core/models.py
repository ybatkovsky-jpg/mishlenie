"""SQLAlchemy ORM models for the Mishlenie bot."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Telegram user with their chosen sphere of application."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str] = mapped_column(String(256), default="Пользователь")
    sphere: Mapped[str] = mapped_column(
        String(64), default="общее развитие"
    )  # работа, бизнес, учёба, личные решения, отношения, общее развитие
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Relationships
    thinking_profiles: Mapped[list["ThinkingProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exercise_sessions: Mapped[list["ExerciseSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversation_history: Mapped[list["ConversationEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ThinkingProfile(Base):
    """Stores score (1-10) for each thinking type per user."""

    __tablename__ = "thinking_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    thinking_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # аналитическое, логическое, критическое, системное, стратегическое, креативное, эмоциональный_интеллект
    score: Mapped[int] = mapped_column(Integer, default=5)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="thinking_profiles")


class ExerciseSession(Base):
    """Record of each exercise attempt: phase, thinking type, task, answer, feedback, score."""

    __tablename__ = "exercise_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    phase: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    thinking_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # NULL for combined tasks
    task_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="exercise_sessions")


class ConversationEntry(Base):
    """Sliding-window conversation history for AI context."""

    __tablename__ = "conversation_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # system, user, assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="conversation_history")
