"""Service for tracking user progress: completed exercises, streaks, stats."""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ExerciseSession, User

logger = logging.getLogger(__name__)


class ProgressService:
    """Tracks exercise completion, streaks, and stats."""

    async def get_stats(self, session: AsyncSession, user: User) -> dict[str, Any]:
        """Get aggregate statistics for a user."""
        # Total exercises completed
        total_result = await session.execute(
            select(func.count(ExerciseSession.id)).where(
                ExerciseSession.user_id == user.id,
                ExerciseSession.score.isnot(None),
            )
        )
        total_completed = total_result.scalar() or 0

        # Unique thinking types attempted
        types_result = await session.execute(
            select(func.count(func.distinct(ExerciseSession.thinking_type))).where(
                ExerciseSession.user_id == user.id,
                ExerciseSession.thinking_type.isnot(None),
            )
        )
        types_completed = types_result.scalar() or 0

        # Current streak (consecutive exercises with score >= 7)
        streak = await self._calculate_streak(session, user)

        # Average score
        avg_result = await session.execute(
            select(func.avg(ExerciseSession.score)).where(
                ExerciseSession.user_id == user.id,
                ExerciseSession.score.isnot(None),
            )
        )
        avg_score = round(avg_result.scalar() or 0, 1)

        return {
            "total_completed": total_completed,
            "types_completed": types_completed,
            "streak": streak,
            "avg_score": avg_score,
        }

    async def _calculate_streak(self, session: AsyncSession, user: User) -> int:
        """Calculate current streak of exercises with score >= 7."""
        result = await session.execute(
            select(ExerciseSession)
            .where(
                ExerciseSession.user_id == user.id,
                ExerciseSession.score.isnot(None),
            )
            .order_by(ExerciseSession.created_at.desc())
            .limit(20)
        )
        sessions = result.scalars().all()

        streak = 0
        for s in sessions:
            if s.score and s.score >= 7:
                streak += 1
            else:
                break
        return streak

    async def record_session(
        self,
        session: AsyncSession,
        user: User,
        phase: int,
        thinking_type: str | None,
        task_text: str | None,
        user_answer: str | None,
        ai_feedback: str | None,
        score: int | None,
    ) -> ExerciseSession:
        """Record an exercise session."""
        exercise = ExerciseSession(
            user_id=user.id,
            phase=phase,
            thinking_type=thinking_type,
            task_text=task_text,
            user_answer=user_answer,
            ai_feedback=ai_feedback,
            score=score,
        )
        session.add(exercise)
        await session.commit()
        await session.refresh(exercise)

        logger.info(
            "Recorded exercise session for user %s: phase=%d type=%s score=%s",
            user.telegram_id,
            phase,
            thinking_type,
            score,
        )
        return exercise

    async def get_recent_sessions(
        self, session: AsyncSession, user: User, limit: int = 5
    ) -> list[ExerciseSession]:
        """Get recent exercise sessions for context."""
        result = await session.execute(
            select(ExerciseSession)
            .where(ExerciseSession.user_id == user.id)
            .order_by(ExerciseSession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


progress_service = ProgressService()
