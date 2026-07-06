"""Service for enhanced progress visualization — radar charts, trends, badges."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ExerciseSession, User

logger = logging.getLogger(__name__)

BADGE_DEFINITIONS = {
    "first_steps": {"name": "🏅 Первые шаги", "desc": "Выполнено 1 задание", "check": lambda u: u.total_sessions >= 1},
    "ten_tasks": {"name": "📝 Десятка", "desc": "Выполнено 10 заданий", "check": lambda u: u.total_sessions >= 10},
    "fifty_tasks": {"name": "💯 Полтинник", "desc": "Выполнено 50 заданий", "check": lambda u: u.total_sessions >= 50},
    "streak_3": {"name": "🔥 На огне", "desc": "Серия из 3 дней", "check": lambda u: (u.daily_streak or 0) >= 3},
    "streak_7": {"name": "⚡ Неделя силы", "desc": "Серия из 7 дней", "check": lambda u: (u.daily_streak or 0) >= 7},
    "streak_30": {"name": "🌟 Месяц огня", "desc": "Серия из 30 дней", "check": lambda u: (u.daily_streak or 0) >= 30},
    "all_types": {"name": "🌈 Коллекционер", "desc": "Все 7 типов мышления пройдены", "check": None},  # requires stats
    "book_3": {"name": "📚 Книжный червь", "desc": "Пройдено 3 главы книг", "check": None},
    "sniper": {"name": "🎯 Снайпер", "desc": "5 оценок 9+ подряд", "check": None},  # requires streak check
    "master_3": {"name": "👑 Мастер мышления", "desc": "Уровень Мастер в 3+ типах", "check": None},
}


class VisualizationService:
    """Generates textual visualizations for thinking profiles."""

    def radar_chart(self, scores: dict[str, int]) -> str:
        """Generate a simple text-based radar chart (6 levels, 7 axes)."""
        type_labels = {
            "analytical": "АНЛ", "logical": "ЛОГ", "critical": "КРИ",
            "systemic": "СИС", "strategic": "СТР", "creative": "КРЕ", "emotional": "ЭМЦ",
        }
        order = ["analytical", "logical", "critical", "systemic", "strategic", "creative", "emotional"]

        levels = ["1-2", "3-4", "5-6", "7-8", "9-10"]
        # Simple horizontal bar alternative for radar
        lines = ["🕸️ <b>Радар мышления:</b>\n"]
        for key in order:
            score = scores.get(key, 5)
            bar = "▓" * (score // 2) + "░" * (5 - score // 2)
            label = type_labels.get(key, key[:3].upper())
            lines.append(f"{label} [{bar}] {score}/10")
        return "\n".join(lines)

    def trend_sparkline(self, score_history: list[int]) -> str:
        """Generate a mini sparkline from score history."""
        if not score_history or len(score_history) < 2:
            return ""
        parts = [str(s) for s in score_history]
        trend = "↑" if score_history[-1] > score_history[0] else ("↓" if score_history[-1] < score_history[0] else "→")
        return " → ".join(parts) + f" {trend}"

    async def get_badges(
        self, session: AsyncSession, user: User, stats: dict[str, Any], levels: dict[str, str]
    ) -> list[dict[str, str]]:
        """Determine which badges the user has earned."""
        current_badges = json.loads(user.badges) if user.badges else []
        new_badges = []

        for key, badge in BADGE_DEFINITIONS.items():
            if key in current_badges:
                continue
            earned = False

            if key == "all_types":
                earned = stats.get("types_completed", 0) >= 7
            elif key == "book_3":
                earned = False  # Requires book progress check — skip for now
            elif key == "sniper":
                # Check last 5 sessions for consecutive 9+
                result = await session.execute(
                    select(ExerciseSession)
                    .where(ExerciseSession.user_id == user.id, ExerciseSession.score.isnot(None))
                    .order_by(ExerciseSession.created_at.desc())
                    .limit(5)
                )
                recent = list(result.scalars().all())
                earned = len(recent) >= 5 and all(s.score and s.score >= 9 for s in recent)
            elif key == "master_3":
                master_count = sum(1 for lvl in levels.values() if lvl in ("master", "expert"))
                earned = master_count >= 3
            elif badge["check"]:
                earned = badge["check"](user)

            if earned:
                new_badges.append({"key": key, "name": badge["name"], "desc": badge["desc"]})
                current_badges.append(key)

        if new_badges:
            user.badges = json.dumps(current_badges)
            await session.commit()

        # Return all badges (current + new)
        all_badges = []
        for key in current_badges:
            badge = BADGE_DEFINITIONS.get(key)
            if badge:
                all_badges.append({"key": key, "name": badge["name"], "desc": badge["desc"], "new": key in [b["key"] for b in new_badges]})
        return all_badges


visualization_service = VisualizationService()
