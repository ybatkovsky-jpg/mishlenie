"""Service for spaced repetition — schedules concept reviews at increasing intervals."""

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ReviewItem, User

logger = logging.getLogger(__name__)

# Review intervals in days: repetition 0→1d, 1→3d, 2→7d, 3→14d, 4+→30d
INTERVALS = [1, 3, 7, 14, 30]


class SpacedRepetitionService:
    """Manages review schedules for thinking concepts."""

    def _next_interval(self, repetition_count: int) -> int:
        """Get the next interval in days for the given repetition count."""
        if repetition_count < len(INTERVALS):
            return INTERVALS[repetition_count]
        return INTERVALS[-1]

    async def schedule_review(
        self,
        session: AsyncSession,
        user: User,
        thinking_type: str,
        concept_keywords: list[str],
        task_summary: str = "",
    ) -> ReviewItem:
        """Create a review item scheduled for future review."""
        interval = self._next_interval(0)
        next_review = datetime.now(UTC) + timedelta(days=interval)

        item = ReviewItem(
            user_id=user.id,
            thinking_type=thinking_type,
            concept_keywords=json.dumps(concept_keywords),
            task_summary=task_summary[:500],
            next_review_at=next_review,
            interval_days=interval,
            repetition_count=0,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        logger.info(
            "Scheduled review for user %s: type=%s keywords=%s next=%s",
            user.telegram_id, thinking_type, concept_keywords,
            next_review.strftime("%Y-%m-%d"),
        )
        return item

    async def get_due_reviews(
        self, session: AsyncSession, user: User
    ) -> list[ReviewItem]:
        """Get all review items that are past their next_review_at date."""
        now = datetime.now(UTC)
        result = await session.execute(
            select(ReviewItem)
            .where(
                ReviewItem.user_id == user.id,
                ReviewItem.next_review_at <= now,
            )
            .order_by(ReviewItem.next_review_at.asc())
            .limit(5)
        )
        return list(result.scalars().all())

    async def complete_review(
        self,
        session: AsyncSession,
        item: ReviewItem,
        passed: bool = True,
    ) -> None:
        """Mark a review as completed and schedule the next one."""
        if passed:
            item.repetition_count += 1
        else:
            # If failed, reset to first interval
            item.repetition_count = 0

        interval = self._next_interval(item.repetition_count)
        item.next_review_at = datetime.now(UTC) + timedelta(days=interval)
        item.interval_days = interval
        await session.commit()

        logger.info(
            "Completed review item %s: new_count=%d next=%s",
            item.id, item.repetition_count,
            item.next_review_at.strftime("%Y-%m-%d"),
        )

    async def get_due_count(
        self, session: AsyncSession, user: User
    ) -> int:
        """Get count of due reviews for display."""
        now = datetime.now(UTC)
        result = await session.execute(
            select(ReviewItem).where(
                ReviewItem.user_id == user.id,
                ReviewItem.next_review_at <= now,
            )
        )
        return len(list(result.scalars().all()))

    async def generate_review_prompt(self, items: list[ReviewItem]) -> str:
        """Generate a prompt for the AI to create a review task."""
        if not items:
            return ""

        concepts = []
        for item in items:
            keywords = json.loads(item.concept_keywords) if item.concept_keywords else []
            concepts.append(
                f"- {item.thinking_type}: {', '.join(keywords)}"
                + (f" (контекст: {item.task_summary[:100]})" if item.task_summary else "")
            )

        concepts_text = "\n".join(concepts)
        return f"""Пользователю нужно повторить ранее изученные концепты. 
Сгенерируй ОДНО короткое микро-задание (50% обычной длины), которое охватывает следующие темы:

{concepts_text}

Формат: короткий сценарий + вопрос. Без теории, сразу к делу.
НЕ используй Markdown."""


spaced_repetition_service = SpacedRepetitionService()
