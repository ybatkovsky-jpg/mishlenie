"""Service for tracking error patterns and adapting task generation."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ErrorPattern, User

logger = logging.getLogger(__name__)

VALID_ERROR_TYPES = {
    "confirmation_bias", "false_dichotomy", "overgeneralization",
    "correlation_causation", "hasty_conclusion", "emotional_reasoning",
    "appeal_to_authority", "slippery_slope", "straw_man", "other",
}


class ErrorAnalyzerService:
    """Aggregates user error patterns and provides adaptation hints."""

    async def record_error(
        self,
        session: AsyncSession,
        user: User,
        error_type: str,
        thinking_type: str | None = None,
    ) -> None:
        """Record or increment an error pattern."""
        if error_type not in VALID_ERROR_TYPES:
            error_type = "other"

        result = await session.execute(
            select(ErrorPattern).where(
                ErrorPattern.user_id == user.id,
                ErrorPattern.error_type == error_type,
                ErrorPattern.thinking_type == thinking_type,
            )
        )
        pattern = result.scalar_one_or_none()

        if pattern:
            pattern.count += 1
        else:
            pattern = ErrorPattern(
                user_id=user.id,
                error_type=error_type,
                thinking_type=thinking_type,
                count=1,
            )
            session.add(pattern)

        await session.commit()
        logger.info(
            "Recorded error pattern for user %s: type=%s count=%d",
            user.telegram_id, error_type, pattern.count,
        )

    async def get_top_errors(
        self, session: AsyncSession, user: User, limit: int = 3
    ) -> list[ErrorPattern]:
        """Get most frequent error patterns for a user."""
        result = await session.execute(
            select(ErrorPattern)
            .where(ErrorPattern.user_id == user.id)
            .order_by(ErrorPattern.count.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_errors_for_type(
        self, session: AsyncSession, user: User, thinking_type: str
    ) -> list[ErrorPattern]:
        """Get error patterns for a specific thinking type."""
        result = await session.execute(
            select(ErrorPattern).where(
                ErrorPattern.user_id == user.id,
                ErrorPattern.thinking_type == thinking_type,
            )
            .order_by(ErrorPattern.count.desc())
        )
        return list(result.scalars().all())

    def format_error_context(self, errors: list[ErrorPattern]) -> str:
        """Format error patterns as context for prompt templates."""
        if not errors:
            return ""

        error_names = {
            "confirmation_bias": "склонность к подтверждению своей точки зрения",
            "false_dichotomy": "ложная дихотомия (или-или)",
            "overgeneralization": "сверхобобщение",
            "correlation_causation": "путаница корреляции и причинности",
            "hasty_conclusion": "поспешные выводы",
            "emotional_reasoning": "эмоциональное обоснование",
            "appeal_to_authority": "апелляция к авторитету",
            "slippery_slope": "скользкий склон",
            "straw_man": "подмена тезиса",
            "other": "прочие ошибки",
        }

        parts = []
        for e in errors:
            name = error_names.get(e.error_type, e.error_type)
            parts.append(f"{name} ({e.count} раз(а))")
        return ", ".join(parts)


error_analyzer_service = ErrorAnalyzerService()
