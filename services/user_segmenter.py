"""Service for behavioral user segmentation into engagement clusters."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import ExerciseSession, User

logger = logging.getLogger(__name__)


class UserSegmenterService:
    """Classifies users into behavioral clusters based on engagement patterns."""

    async def classify_user(self, session: AsyncSession, user: User) -> str:
        """Assign a behavioral segment to a user.

        Returns one of: strategic, routine, reactive, sporadic, unknown.
        """
        now = datetime.now(UTC)

        # Get all exercise sessions for this user
        result = await session.execute(
            select(ExerciseSession)
            .where(ExerciseSession.user_id == user.id)
            .order_by(ExerciseSession.created_at.asc())
        )
        sessions = list(result.scalars().all())

        if not sessions:
            return "unknown"

        # Helper to safely get days difference (handle naive datetimes from old DB)
        def safe_days_diff(dt1: datetime, dt2: datetime) -> int:
            if dt1.tzinfo is None:
                dt1 = dt1.replace(tzinfo=UTC)
            if dt2.tzinfo is None:
                dt2 = dt2.replace(tzinfo=UTC)
            return abs((dt1 - dt2).days)

        first_session = sessions[0].created_at
        last_session = sessions[-1].created_at
        total_days = max(1, safe_days_diff(now, first_session))

        # Active days (unique dates with activity)
        active_dates = {s.created_at.date() for s in sessions}
        active_days = len(active_dates)
        active_ratio = active_days / total_days

        # Average session length (sessions per active day)
        # Fix naive datetimes in sessions for comparison
        def ensure_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

        active_dates = {ensure_utc(s.created_at).date() for s in sessions}
        active_days = len(active_dates)
        avg_sessions_per_day = len(sessions) / max(1, active_days)

        # Retention: did they come back after 7+ days?
        returned_after_gap = False
        for i in range(1, len(sessions)):
            gap = safe_days_diff(
                ensure_utc(sessions[i].created_at),
                ensure_utc(sessions[i-1].created_at),
            )
            if gap >= 7 and i > 2:
                returned_after_gap = True
                break

        # Classify
        if total_days < 3:
            segment = "sporadic"
        elif active_ratio >= 0.8 and avg_sessions_per_day >= 0.8:
            segment = "routine"
        elif total_days >= 30 and avg_sessions_per_day >= 1.5:
            segment = "strategic"
        elif returned_after_gap or (active_ratio >= 0.2 and active_ratio < 0.8):
            segment = "reactive"
        else:
            segment = "sporadic"

        # Update user
        user.segment = segment
        user.segment_updated_at = now
        await session.commit()

        logger.info(
            "Classified user %s as '%s' (days=%d, active_ratio=%.2f, avg_sessions=%.1f)",
            user.telegram_id, segment, total_days, active_ratio, avg_sessions_per_day,
        )
        return segment

    async def should_reclassify(self, user: User) -> bool:
        """Check if user should be reclassified (once per week)."""
        if not user.segment_updated_at:
            return True
        week_ago = datetime.now(UTC) - timedelta(days=7)
        return user.segment_updated_at < week_ago

    def get_segment_settings(self, segment: str) -> dict:
        """Get UX settings for each segment."""
        settings = {
            "strategic": {
                "max_tokens": 2048,
                "show_skip": False,
                "long_session_button": True,
                "tempo": "fast",
            },
            "routine": {
                "max_tokens": 1536,
                "show_skip": False,
                "long_session_button": False,
                "tempo": "steady",
            },
            "reactive": {
                "max_tokens": 1536,
                "show_skip": True,
                "long_session_button": True,
                "tempo": "burst",
            },
            "sporadic": {
                "max_tokens": 1024,
                "show_skip": True,
                "long_session_button": False,
                "tempo": "gentle",
            },
            "unknown": {
                "max_tokens": 1536,
                "show_skip": False,
                "long_session_button": False,
                "tempo": "steady",
            },
        }
        return settings.get(segment, settings["unknown"])


user_segmenter_service = UserSegmenterService()
