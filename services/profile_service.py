"""Service for managing user thinking profiles — scores per thinking type."""

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ExerciseSession, ThinkingProfile, User

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

# Mastery level thresholds
LEVEL_THRESHOLDS = {
    "novice": (1, 4),
    "practitioner": (5, 7),
    "master": (8, 9),
    "expert": (10, 10),
}


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
    ) -> str | None:
        """Update a thinking type score (clamped 1-10) using cumulative averaging.

        Returns the new mastery level if it changed, otherwise None.
        """
        new_score = max(1, min(10, new_score))

        result = await session.execute(
            select(ThinkingProfile).where(
                ThinkingProfile.user_id == user.id,
                ThinkingProfile.thinking_type == thinking_type,
            )
        )
        profile = result.scalar_one_or_none()

        if not profile:
            profile = ThinkingProfile(
                user_id=user.id,
                thinking_type=thinking_type,
                score=new_score,
                score_history=json.dumps([new_score]),
                current_level="novice",
            )
            session.add(profile)
            await session.commit()
            logger.info(
                "Created thinking profile for user %s: %s = %d",
                user.telegram_id, thinking_type, new_score,
            )
            return None

        # Cumulative scoring: keep last 5 scores, compute weighted average
        history = json.loads(profile.score_history) if profile.score_history else []
        history.append(new_score)
        if len(history) > 5:
            history = history[-5:]

        # Weighted: 60% historical average + 40% latest score
        avg_history = sum(history[:-1]) / len(history[:-1]) if len(history) > 1 else new_score
        cumulative_score = round(avg_history * 0.6 + new_score * 0.4)
        cumulative_score = max(1, min(10, cumulative_score))

        old_level = profile.current_level
        new_level = self._calculate_level(cumulative_score, len(history))

        profile.score = cumulative_score
        profile.score_history = json.dumps(history)
        profile.current_level = new_level
        await session.commit()

        level_changed = new_level if new_level != old_level else None

        logger.info(
            "Updated thinking profile for user %s: %s = %d (history=%s, level=%s)",
            user.telegram_id, thinking_type, cumulative_score,
            history, new_level,
        )
        return level_changed

    @staticmethod
    def _calculate_level(score: int, exercise_count: int) -> str:
        """Determine mastery level based on cumulative score and exercise count."""
        if score >= 10 and exercise_count >= 10:
            return "expert"
        elif score >= 8 and exercise_count >= 5:
            return "master"
        elif score >= 5:
            return "practitioner"
        else:
            return "novice"

    async def get_trend(self, scores: dict[str, int], session: AsyncSession, user: User) -> dict[str, str]:
        """Calculate trend direction (↑/↓/→) for each thinking type."""
        trends: dict[str, str] = {}
        for ttype in THINKING_TYPES:
            result = await session.execute(
                select(ThinkingProfile).where(
                    ThinkingProfile.user_id == user.id,
                    ThinkingProfile.thinking_type == ttype,
                )
            )
            profile = result.scalar_one_or_none()
            if profile and profile.score_history:
                history = json.loads(profile.score_history)
                if len(history) >= 2:
                    if history[-1] > history[-2]:
                        trends[ttype] = "↑"
                    elif history[-1] < history[-2]:
                        trends[ttype] = "↓"
                    else:
                        trends[ttype] = "→"
                else:
                    trends[ttype] = ""
            else:
                trends[ttype] = ""
        return trends

    async def get_scores(
        self, session: AsyncSession, user: User
    ) -> dict[str, int]:
        """Get current scores for all thinking types."""
        return await self.get_or_create_profiles(session, user)

    async def get_levels(
        self, session: AsyncSession, user: User
    ) -> dict[str, str]:
        """Get current mastery levels for all thinking types."""
        result = await session.execute(
            select(ThinkingProfile).where(ThinkingProfile.user_id == user.id)
        )
        return {p.thinking_type: p.current_level for p in result.scalars().all()}

    async def get_lowest_types(
        self, session: AsyncSession, user: User, count: int = 3
    ) -> list[str]:
        """Get thinking types with the lowest scores."""
        scores = await self.get_scores(session, user)
        sorted_types = sorted(scores.items(), key=lambda x: x[1])
        return [t for t, s in sorted_types[:count]]

    def format_profile(self, scores: dict[str, int], trends: dict[str, str] | None = None, levels: dict[str, str] | None = None) -> str:
        """Format profile as emoji-bar chart with trends and mastery levels."""
        from prompts.templates import get_thinking_type_name

        level_emoji = {
            "novice": "🌱",
            "practitioner": "🌿",
            "master": "🌳",
            "expert": "👑",
        }

        lines = ["🧠 <b>Ваш профиль мышления:</b>\n"]
        for key in THINKING_TYPES:
            score = scores.get(key, DEFAULT_SCORE)
            bar = "█" * score + "░" * (10 - score)
            name = get_thinking_type_name(key)
            trend = (trends or {}).get(key, "")
            lvl = (levels or {}).get(key, "")
            lvl_emoji = level_emoji.get(lvl, "")
            marker = "  ← зона роста" if score <= 4 else ""
            lines.append(f"{lvl_emoji} {name:<20} {bar} {score}/10 {trend}{marker}")
        return "\n".join(lines)


profile_service = ProfileService()
