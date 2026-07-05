"""Handler for Phase 4: Combined tasks using 2-3 thinking types."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards import after_feedback_keyboard, continue_keyboard, thinking_type_keyboard
from bot.states import TrainerStates
from core.database import async_session_factory
from core.models import User
from services.ai_service import ai_service
from services.profile_service import profile_service
from services.progress_service import progress_service

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(TrainerStates.combined_task, F.data == "continue")
async def on_combined_continue(callback: CallbackQuery, state: FSMContext) -> None:
    """User ready to answer combined task."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✍️ <b>Ваш ответ на комбинированное задание:</b>\n\n"
        "Опишите ваши рассуждения. Помните: в этом задании нужно применить "
        "2-3 вида мышления одновременно. Покажите, как вы комбинируете подходы.",
    )
    await state.set_state(TrainerStates.combined_answer)


@router.message(TrainerStates.combined_answer)
async def on_combined_answer(message: Message, state: FSMContext) -> None:
    """User answered a combined task — get AI feedback using reasoner."""
    if not message.text or not message.from_user:
        await message.answer("Пожалуйста, напишите текстовый ответ.")
        return

    data = await state.get_data()
    task_text = data.get("current_task", "")

    feedback_msg = await message.answer("⏳ Анализирую ваш ответ (использую DeepSeek Reasoner)...")

    # Get feedback — always use reasoner for combined
    feedback_text = await ai_service.get_feedback(
        thinking_type="combined",
        task=task_text,
        answer=message.text,
        use_reasoner=True,
    )

    # Extract score
    import re
    match = re.search(r"[Оо]ценка[^:]*:\s*(\d+)/10", feedback_text)
    score = int(match.group(1)) if match else None

    # Record session
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            await progress_service.record_session(
                session=session,
                user=user,
                phase=4,
                thinking_type=None,  # combined
                task_text=task_text,
                user_answer=message.text,
                ai_feedback=feedback_text,
                score=score,
            )
            stats = await progress_service.get_stats(session, user)
            show_combined = stats["types_completed"] >= 3

    await feedback_msg.edit_text(feedback_text)

    await message.answer(
        "👇 <b>Что дальше?</b>",
        reply_markup=after_feedback_keyboard(
            thinking_type="combined",
            show_combined=show_combined,
        ),
    )
    await state.set_state(TrainerStates.feedback_view)
