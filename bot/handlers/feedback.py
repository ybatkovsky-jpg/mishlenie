"""Handler for Phase 3: Feedback — analyze user's answer and provide feedback."""

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards import after_feedback_keyboard, thinking_type_keyboard
from bot.states import TrainerStates
from core.database import async_session_factory
from core.models import User
from services.ai_service import ai_service
from services.profile_service import profile_service
from services.progress_service import progress_service

logger = logging.getLogger(__name__)

router = Router()


@router.message(TrainerStates.awaiting_answer)
async def on_answer_received(message: Message, state: FSMContext) -> None:
    """User submitted their answer to a training task — get AI feedback."""
    if not message.text or not message.from_user:
        await message.answer("Пожалуйста, напишите текстовый ответ.")
        return

    data = await state.get_data()
    thinking_type = data.get("current_thinking_type", "analytical")
    task_text = data.get("current_task", "")

    feedback_msg = await message.answer("⏳ Анализирую ваш ответ...")

    # Get AI feedback
    use_reasoner = (thinking_type == "combined")
    feedback_text = await ai_service.get_feedback(
        thinking_type=thinking_type,
        task=task_text,
        answer=message.text,
        use_reasoner=use_reasoner,
    )

    # Extract score from feedback text
    score = _extract_score(feedback_text)

    # Record session in DB
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            # Record exercise
            await progress_service.record_session(
                session=session,
                user=user,
                phase=3 if thinking_type != "combined" else 4,
                thinking_type=thinking_type if thinking_type != "combined" else None,
                task_text=task_text,
                user_answer=message.text,
                ai_feedback=feedback_text,
                score=score,
            )

            # Update thinking profile with new score
            if score and thinking_type != "combined":
                current_scores = data.get("current_scores", {})
                current_scores[thinking_type] = score
                await profile_service.update_score(session, user, thinking_type, score)
                await state.update_data(current_scores=current_scores)

            # Get stats for combined eligibility
            stats = await progress_service.get_stats(session, user)
            show_combined = stats["types_completed"] >= 3

    # Show feedback to user
    await feedback_msg.edit_text(feedback_text)

    # Show next action keyboard
    await message.answer(
        "👇 <b>Что дальше?</b>",
        reply_markup=after_feedback_keyboard(
            thinking_type=thinking_type,
            show_combined=show_combined,
        ),
    )
    await state.set_state(TrainerStates.feedback_view)


@router.callback_query(TrainerStates.feedback_view, F.data == "next_same")
async def on_next_same(callback: CallbackQuery, state: FSMContext) -> None:
    """User wants another task of the same thinking type."""
    data = await state.get_data()
    thinking_type = data.get("current_thinking_type", "analytical")
    sphere = data.get("sphere", "общее развитие")
    difficulty = data.get("difficulty", 0)

    await callback.message.answer(
        f"⏳ Готовлю следующее задание по виду мышления: "
        f"<b>{_type_name(thinking_type)}</b>...",
    )

    task_text = await ai_service.get_training_task(
        thinking_type=thinking_type,
        sphere=sphere,
        difficulty=difficulty,
        use_reasoner=False,
    )

    await state.update_data(current_task=task_text)
    await callback.message.answer(task_text, reply_markup=_continue_keyboard())
    await state.set_state(TrainerStates.training_task)


@router.callback_query(TrainerStates.feedback_view, F.data == "type_combined")
async def on_combined_from_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    """Start combined task from feedback view."""
    from bot.handlers.training import start_combined_task
    await start_combined_task(callback, state)


def _extract_score(text: str) -> int | None:
    """Extract score like '7/10' or '⭐ Оценка задания: 8/10' from feedback text."""
    # Try explicit pattern first
    match = re.search(r"[Оо]ценка[^:]*:\s*(\d+)/10", text)
    if match:
        return int(match.group(1))

    # Fallback: any X/10
    match = re.search(r"(\d+)/10", text)
    if match:
        score = int(match.group(1))
        if 1 <= score <= 10:
            return score
    return None


def _continue_keyboard():
    from bot.keyboards import continue_keyboard
    return continue_keyboard()


def _type_name(key: str) -> str:
    from prompts.templates import get_thinking_type_name
    return get_thinking_type_name(key)
