"""Service for managing user thinking profiles — scores per thinking type."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ThinkingProfile, User

logger = logging.getLogger(__name__)

THINKING_TYPES = [
    "analytical",
    "logical",
    "critical",
    "systemic",
    "strategic",
    "creative",
    "emotional",
]

DEFAULT_SCORE = 5


class ProfileService:
    """CRUD operations for thinking profiles."""

    async def get_or_create_profiles(
        self, session: AsyncSession, user: User
    ) -> dict[str, int]:
        """Get existing scores or create default profiles. Returns {type_key: score}."""
        result = await session.execute(
            select(ThinkingProfile).where(ThinkingProfile.user_id == user.id)
        )
        existing = {p.thinking_type: p for p in result.scalars().all()}

        profiles: dict[str, int] = {}
        for ttype in THINKING_TYPES:
            if ttype in existing:
                profiles[ttype] = existing[ttype].score
            else:
                profile = ThinkingProfile(
                    user_id=user.id,
                    thinking_type=ttype,
                    score=DEFAULT_SCORE,
                )
                session.add(profile)
                profiles[ttype] = DEFAULT_SCORE

        await session.commit()
        return profiles

    async def update_score(
        self,
        session: AsyncSession,
        user: User,
        thinking_type: str,
        new_score: int,
    ) -> None:
        """Update a thinking type score (clamped 1-10)."""
        new_score = max(1, min(10, new_score))

        result = await session.execute(
            select(ThinkingProfile).where(
                ThinkingProfile.user_id == user.id,
                ThinkingProfile.thinking_type == thinking_type,
            )
        )
        profile = result.scalar_one_or_none()

        if profile:
            profile.score = new_score
        else:
            profile = ThinkingProfile(
                user_id=user.id,
                thinking_type=thinking_type,
                score=new_score,
            )
            session.add(profile)

        await session.commit()
        logger.info(
            "Updated thinking profile for user %s: %s = %d",
            user.telegram_id,
            thinking_type,
            new_score,
        )

    async def get_scores(
        self, session: AsyncSession, user: User
    ) -> dict[str, int]:
        """Get current scores for all thinking types."""
        return await self.get_or_create_profiles(session, user)

    async def get_lowest_types(
        self, session: AsyncSession, user: User, count: int = 3
    ) -> list[str]:
        """Get thinking types with the lowest scores."""
        scores = await self.get_scores(session, user)
        sorted_types = sorted(scores.items(), key=lambda x: x[1])
        return [t for t, s in sorted_types[:count]]

    def format_profile(self, scores: dict[str, int]) -> str:
        """Format profile as emoji-bar chart."""
        from prompts.templates import get_thinking_type_name

        lines = ["🧠 Ваш профиль мышления:\n"]
        for key in THINKING_TYPES:
            score = scores.get(key, DEFAULT_SCORE)
            bar = "█" * score + "░" * (10 - score)
            name = get_thinking_type_name(key)
            marker = "  ← зона роста" if score <= 4 else ""
            lines.append(f"{name:<20} {bar} {score}/10{marker}")
        return "\n".join(lines)


profile_service = ProfileService()
