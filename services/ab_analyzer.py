"""Service for A/B testing prompt variants — comparing effectiveness."""

import hashlib
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ExerciseSession

logger = logging.getLogger(__name__)


class ABAnalyzerService:
    """Compares prompt variant performance using exercise session data."""

    @staticmethod
    def get_variant(user_id: str, prompt_name: str) -> str:
        """Deterministically assign A or B variant based on user_id hash."""
        hash_input = f"{user_id}:{prompt_name}"
        hash_val = int(hashlib.md5(hash_input.encode()).hexdigest()[:8], 16)
        return "A" if hash_val % 2 == 0 else "B"

    async def compare_variants(
        self, session: AsyncSession, prompt_name: str
    ) -> dict:
        """Compare A vs B variants for a given prompt.

        Returns dict with avg_score, count, avg_answer_length for each variant.
        """
        # Get sessions from last 30 days with prompt_version set
        cutoff = datetime.now() - timedelta(days=30)

        result_a = await session.execute(
            select(
                func.avg(ExerciseSession.score),
                func.count(ExerciseSession.id),
            ).where(
                ExerciseSession.prompt_version == "A",
                ExerciseSession.score.isnot(None),
                ExerciseSession.created_at >= cutoff,
            )
        )
        row_a = result_a.one()
        avg_score_a = round(row_a[0] or 0, 1)
        count_a = row_a[1] or 0

        result_b = await session.execute(
            select(
                func.avg(ExerciseSession.score),
                func.count(ExerciseSession.id),
            ).where(
                ExerciseSession.prompt_version == "B",
                ExerciseSession.score.isnot(None),
                ExerciseSession.created_at >= cutoff,
            )
        )
        row_b = result_b.one()
        avg_score_b = round(row_b[0] or 0, 1)
        count_b = row_b[1] or 0

        winner = None
        if count_a >= 10 and count_b >= 10:
            if avg_score_a > avg_score_b:
                winner = "A"
            elif avg_score_b > avg_score_a:
                winner = "B"

        return {
            "prompt_name": prompt_name,
            "A": {"avg_score": avg_score_a, "count": count_a},
            "B": {"avg_score": avg_score_b, "count": count_b},
            "winner": winner,
        }


ab_analyzer_service = ABAnalyzerService()
