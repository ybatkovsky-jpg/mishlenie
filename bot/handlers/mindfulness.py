"""Handler for Phase 5: Mindfulness exercises and integration."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import mindfulness_choice_keyboard, thinking_type_keyboard
from bot.states import TrainerStates
from services.ai_service import ai_service

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "mindfulness")
async def on_mindfulness_request(callback: CallbackQuery, state: FSMContext) -> None:
    """User requested a mindfulness exercise."""
    await callback.message.answer("⏳ Подбираю упражнение на осознанность...")

    exercise_text = await ai_service.get_mindfulness_exercise()

    await callback.message.answer(exercise_text, reply_markup=mindfulness_choice_keyboard())
    await state.set_state(TrainerStates.mindfulness_break)


@router.callback_query(TrainerStates.mindfulness_break, F.data == "choose_type")
async def on_mindfulness_back_to_training(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to training after mindfulness."""
    data = await state.get_data()
    scores = data.get("current_scores", {})

    await callback.message.answer(
        "🎯 <b>Выберите вид мышления для тренировки:</b>",
        reply_markup=thinking_type_keyboard(current_scores=scores),
    )
    await state.set_state(TrainerStates.training_choice)


@router.callback_query(TrainerStates.mindfulness_break, F.data == "profile")
async def on_mindfulness_to_profile(callback: CallbackQuery, state: FSMContext) -> None:
    """Show profile from mindfulness break."""
    from sqlalchemy import select
    from core.database import async_session_factory
    from core.models import User
    from services.profile_service import profile_service

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            scores = await profile_service.get_scores(session, user)
            levels = await profile_service.get_levels(session, user)
            trends = await profile_service.get_trend(scores, session, user)
            profile_text = profile_service.format_profile(scores, trends, levels)
        else:
            profile_text = "Профиль не найден."

    await callback.message.answer(profile_text, reply_markup=thinking_type_keyboard(current_scores=scores))
    await state.set_state(TrainerStates.training_choice)


@router.callback_query(TrainerStates.mindfulness_break, F.data == "stats")
async def on_mindfulness_stats(callback: CallbackQuery, state: FSMContext) -> None:
    """Show stats from mindfulness break."""
    from sqlalchemy import select
    from core.database import async_session_factory
    from core.models import User
    from services.progress_service import progress_service

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            stats = await progress_service.get_stats(session, user)
        else:
            stats = {"total_completed": 0, "types_completed": 0, "streak": 0, "avg_score": 0}

    streak_text = f"🔥 Серия: {stats['streak']} заданий подряд (оценка 7+)" if stats["streak"] >= 3 else ""

    stats_text = (
        f"📊 <b>Ваша статистика:</b>\n\n"
        f"📝 Заданий выполнено: <b>{stats['total_completed']}</b>\n"
        f"🎯 Видов мышления пройдено: <b>{stats['types_completed']}/7</b>\n"
        f"⭐ Средняя оценка: <b>{stats['avg_score']}/10</b>\n"
        f"{streak_text}"
    )

    await callback.message.answer(stats_text)
    await callback.answer()
