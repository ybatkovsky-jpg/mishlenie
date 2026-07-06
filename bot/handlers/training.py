"""Handler for Phase 2: Training — deep dive into a thinking type."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards import (
    after_feedback_keyboard,
    continue_keyboard,
    difficulty_keyboard,
    thinking_type_keyboard,
)
from bot.states import TrainerStates
from core.database import async_session_factory
from core.models import User
from services.ai_service import ai_service
from services.profile_service import profile_service
from services.progress_service import progress_service

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(TrainerStates.training_choice, F.data.startswith("type_"))
async def on_training_type_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    """User chose a thinking type to train — generate a task."""
    if not callback.data or not callback.from_user:
        return

    thinking_type = callback.data.replace("type_", "")
    data = await state.get_data()
    sphere = data.get("sphere", "общее развитие")
    difficulty = data.get("difficulty", 0)

    if thinking_type == "combined":
        await start_combined_task(callback, state)
        return

    await callback.message.answer(
        f"⏳ Готовлю задание по виду мышления: "
        f"<b>{_type_name(thinking_type)}</b>...",
    )

    # Generate training task
    task_text = await ai_service.get_training_task(
        thinking_type=thinking_type,
        sphere=sphere,
        difficulty=difficulty,
        use_reasoner=False,
    )

    # Store task info
    await state.update_data(
        current_thinking_type=thinking_type,
        current_task=task_text,
    )

    await callback.message.answer(task_text, reply_markup=continue_keyboard())
    await state.set_state(TrainerStates.training_task)


@router.callback_query(TrainerStates.training_task, F.data == "continue")
async def on_continue_to_answer(callback: CallbackQuery, state: FSMContext) -> None:
    """User ready to answer after mindfulness pause."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✍️ <b>Ваш ответ:</b>\n\n"
        "Опишите ваши рассуждения и решение. Не бойтесь ошибиться — "
        "важен процесс мышления, а не «правильный» ответ.",
    )
    await state.set_state(TrainerStates.awaiting_answer)


@router.callback_query(F.data == "choose_type")
async def on_choose_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Show thinking type selection keyboard."""
    data = await state.get_data()
    scores = data.get("current_scores", {})

    # Check if user completed at least 3 types for combined tasks
    stats_data = await state.get_data()
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            stats = await progress_service.get_stats(session, user)
            show_combined = stats["types_completed"] >= 3
        else:
            show_combined = False

    await callback.message.answer(
        "🎯 <b>Выберите вид мышления для тренировки:</b>",
        reply_markup=thinking_type_keyboard(
            show_combined=show_combined,
            current_scores=scores,
        ),
    )
    await state.set_state(TrainerStates.training_choice)


@router.callback_query(F.data == "profile")
async def on_show_profile(callback: CallbackQuery, state: FSMContext) -> None:
    """Show current thinking profile."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден.")
            return

        scores = await profile_service.get_scores(session, user)
        levels = await profile_service.get_levels(session, user)
        trends = await profile_service.get_trend(scores, session, user)
        stats = await progress_service.get_stats(session, user)

        from services.visualization import visualization_service
        badges = await visualization_service.get_badges(session, user, stats, levels)

    profile_text = profile_service.format_profile(scores, trends, levels)

    # Add badges if any
    badge_text = ""
    if badges:
        new_badges = [b for b in badges if b.get("new")]
        badge_lines = ["\n🏆 <b>Достижения:</b>"]
        for b in badges:
            marker = " 🆕" if b in new_badges else ""
            badge_lines.append(f"{b['name']}{marker} — {b['desc']}")
        badge_text = "\n".join(badge_lines)

    # Announce new badges
    if new_badges:
        for b in new_badges:
            await callback.message.answer(f"🎉 Новое достижение: <b>{b['name']}</b> — {b['desc']}!")

    await callback.message.answer(
        profile_text + badge_text,
        reply_markup=thinking_type_keyboard(current_scores=scores, current_trends=trends),
    )
    await state.set_state(TrainerStates.training_choice)


@router.callback_query(F.data == "stats")
async def on_show_stats(callback: CallbackQuery, state: FSMContext) -> None:
    """Show user statistics."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден.")
            return

        stats = await progress_service.get_stats(session, user)

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


# --- Helper for starting combined tasks (called from this router and combined.py) ---

async def start_combined_task(callback: CallbackQuery, state: FSMContext) -> None:
    """Start a combined (Phase 4) task."""
    data = await state.get_data()
    sphere = data.get("sphere", "общее развитие")

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return
        stats = await progress_service.get_stats(session, user)

    if stats["types_completed"] < 3:
        await callback.message.answer(
            "⚠️ Комбинированные задания открываются после прохождения минимум 3 видов мышления.\n"
            f"Сейчас пройдено: <b>{stats['types_completed']}/3</b>.",
            reply_markup=thinking_type_keyboard(),
        )
        return

    await callback.message.answer("⏳ Готовлю комбинированное задание... (использую DeepSeek Reasoner)")

    # Use the user's actually completed thinking types
    completed_types = stats["completed_type_names"]
    # If somehow empty (shouldn't happen since we checked types_completed >= 3), fallback
    if not completed_types:
        completed_types = ["analytical", "logical", "critical"]

    task_text = await ai_service.get_combined_task(
        completed_types=completed_types,
        sphere=sphere,
    )

    await state.update_data(
        current_thinking_type="combined",
        current_task=task_text,
    )

    await callback.message.answer(task_text, reply_markup=continue_keyboard())
    await state.set_state(TrainerStates.combined_task)


def _type_name(key: str) -> str:
    """Get Russian name for thinking type."""
    from prompts.templates import get_thinking_type_name
    return get_thinking_type_name(key)
