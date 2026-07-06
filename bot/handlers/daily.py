"""Handler for /daily command — one short task per day with streak tracking."""

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from bot.keyboards import after_feedback_keyboard, continue_keyboard
from bot.states import TrainerStates
from core.database import async_session_factory
from core.models import User
from services.ai_service import ai_service
from services.profile_service import profile_service
from services.progress_service import progress_service

logger = logging.getLogger(__name__)

router = Router()

# Day-of-week → thinking type mapping
DAILY_TYPES = {
    0: "analytical",    # Monday
    1: "creative",       # Tuesday
    2: "systemic",       # Wednesday
    3: "critical",       # Thursday
    4: "strategic",      # Friday
    5: "logical",        # Saturday
    6: "emotional",      # Sunday
}


@router.message(Command("daily"))
async def cmd_daily(message: Message, state: FSMContext) -> None:
    """Generate a short daily task based on the day of the week."""
    if not message.from_user:
        return

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Сначала выполните /start для настройки профиля.")
            return

        # Check if already done today
        now = datetime.now(UTC)
        if user.last_daily_at:
            last = user.last_daily_at
            if last.date() == now.date():
                streak_text = (
                    f"🔥 Серия: <b>{user.daily_streak}</b> дн. подряд"
                    if user.daily_streak >= 3
                    else f"📅 Серия: {user.daily_streak} дн."
                )
                await message.answer(
                    f"✅ Вы уже выполнили ежедневное задание сегодня!\n"
                    f"{streak_text}\n\n"
                    f"Возвращайтесь завтра за новым заданием. "
                    f"А пока можете продолжить обычную тренировку — /start"
                )
                return

            # Calculate streak
            yesterday = (now - timedelta(days=1)).date()
            if last.date() == yesterday:
                user.daily_streak += 1
            else:
                user.daily_streak = 1
        else:
            user.daily_streak = 1

        user.last_daily_at = now
        await session.commit()

        sphere = user.sphere

    # Pick thinking type by day of week
    thinking_type = DAILY_TYPES[now.weekday()]

    await message.answer(
        f"📅 <b>Ежедневное задание</b> — {_day_name(now.weekday())}\n"
        f"🎯 Вид мышления: <b>{_type_name(thinking_type)}</b>\n"
        f"⏳ Готовлю короткое задание (3-5 минут)..."
    )

    # Generate a short daily task
    from prompts.system_prompt import SYSTEM_PROMPT_COMPACT

    daily_prompt = f"""Сгенерируй КОРОТКОЕ ежедневное задание по виду мышления: {_type_name(thinking_type)}.
Сфера пользователя: {sphere}.

Правила для daily-задания:
- ТОЛЬКО практический сценарий + вопрос (без теории)
- Очень коротко: 3-5 предложений сценарий + 1 вопрос
- Без mindfulness-паузы, без структуры «теория-пример-задание»
- Сразу к делу
- НЕ используй Markdown

Формат:
🎯 [Одно предложение-заголовок]
[Короткий сценарий]
💬 [Один конкретный вопрос]"""

    task_text = await ai_service.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": daily_prompt},
        ],
        temperature=0.7, max_tokens=800,
    )

    # Store task info in FSM
    await state.update_data(
        current_thinking_type=thinking_type,
        current_task=task_text,
        is_daily=True,
    )

    streak_badge = "🔥" if user.daily_streak >= 3 else "📅"
    await message.answer(
        f"{task_text}\n\n"
        f"{streak_badge} Серия: <b>{user.daily_streak}</b> дн. подряд",
        reply_markup=continue_keyboard(),
    )
    await state.set_state(TrainerStates.training_task)


def _day_name(weekday: int) -> str:
    """Get Russian day name."""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[weekday]


def _type_name(key: str) -> str:
    from prompts.templates import get_thinking_type_name
    return get_thinking_type_name(key)
