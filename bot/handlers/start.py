"""Handler for /start command — welcome message and sphere selection."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards import sphere_keyboard
from bot.states import TrainerStates
from core.database import async_session_factory
from core.models import User
from services.profile_service import profile_service

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start — greet user and ask for their sphere of application."""
    if not message.from_user:
        return

    # Ensure user exists in DB
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "Пользователь",
            )
            session.add(user)
            await session.commit()
            logger.info("Created new user: telegram_id=%d", message.from_user.id)
        else:
            # Update username/name if changed
            user.username = message.from_user.username
            user.first_name = message.from_user.first_name or user.first_name
            await session.commit()

    welcome_text = (
        "🧠 <b>Добро пожаловать в Тренажер Мышления!</b>\n\n"
        "Я помогу вам прокачать 7 видов мышления — от аналитического до креативного — "
        "через реальные сценарии и практические задания. Плюс мы добавим упражнения на "
        "осознанность, чтобы вы научились замечать, <i>как именно</i> вы думаете.\n\n"
        "<b>Как это работает:</b>\n"
        "1. Сначала — экспресс-диагностика (7 мини-ситуаций)\n"
        "2. Затем — персональная программа с заданиями и обратной связью\n"
        "3. Постепенно — комбинированные сценарии, где виды мышления работают вместе\n\n"
        "Для начала выберите:\n"
        "<b>В какой сфере вы хотите применять развитие мышления?</b>"
    )

    await message.answer(welcome_text, reply_markup=sphere_keyboard())
    await state.set_state(TrainerStates.sphere_selection)


@router.callback_query(TrainerStates.sphere_selection, F.data.startswith("sphere_"))
async def on_sphere_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle sphere selection, save it, and start diagnostics."""
    if not callback.data or not callback.from_user:
        return

    sphere = callback.data.replace("sphere_", "")

    # Save sphere in DB
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.sphere = sphere
            await session.commit()

    # Store in FSM data
    await state.update_data(sphere=sphere, diagnostics_answers=[], diagnostics_current=0)

    await callback.message.edit_text(
        f"✅ Сфера: <b>{sphere}</b>\n\n"
        "Отлично! Теперь проведём экспресс-диагностику.\n"
        "Я задам 7 коротких вопросов-сценариев — по одному на каждый вид мышления.\n"
        "Отвечайте развёрнуто: описывайте, как вы действовали бы в такой ситуации.\n\n"
        "Готовы? Начинаем! 🚀",
    )

    # Start first diagnostic question
    await start_diagnostic_question(callback, state, 0)


async def start_diagnostic_question(
    callback: CallbackQuery, state: FSMContext, question_index: int
) -> None:
    """Send a diagnostic question for the given index (0-6)."""
    from services.ai_service import ai_service

    thinking_types = [
        "analytical", "logical", "critical", "systemic",
        "strategic", "creative", "emotional",
    ]
    thinking_names = [
        "Аналитическое", "Логическое", "Критическое", "Системное",
        "Стратегическое", "Креативное", "Эмоциональный интеллект",
    ]
    state_names = [
        TrainerStates.diagnostics_q1, TrainerStates.diagnostics_q2,
        TrainerStates.diagnostics_q3, TrainerStates.diagnostics_q4,
        TrainerStates.diagnostics_q5, TrainerStates.diagnostics_q6,
        TrainerStates.diagnostics_q7,
    ]

    data = await state.get_data()
    sphere = data.get("sphere", "общее развитие")
    answers = data.get("diagnostics_answers", [])

    thinking_msg = await callback.message.answer(
        f"⏳ Готовлю вопрос #{question_index + 1}/7 ({thinking_names[question_index]})...",
    )

    # Get question from AI
    question = await ai_service.get_diagnostic_question(
        sphere=sphere,
        thinking_type=thinking_types[question_index],
        question_number=question_index + 1,
        previous_answers=answers if question_index > 0 else None,
    )

    await thinking_msg.edit_text(question)

    await state.update_data(
        diagnostics_current=question_index,
        current_thinking_type=thinking_types[question_index],
    )
    await state.set_state(state_names[question_index])


@router.message(TrainerStates.diagnostics_q1)
@router.message(TrainerStates.diagnostics_q2)
@router.message(TrainerStates.diagnostics_q3)
@router.message(TrainerStates.diagnostics_q4)
@router.message(TrainerStates.diagnostics_q5)
@router.message(TrainerStates.diagnostics_q6)
async def on_diagnostic_answer(message: Message, state: FSMContext) -> None:
    """Receive answer to a diagnostic question and move to next."""
    if not message.text:
        await message.answer("Пожалуйста, напишите текстовый ответ.")
        return

    data = await state.get_data()
    answers: list[str] = data.get("diagnostics_answers", [])
    current: int = data.get("diagnostics_current", 0)

    answers.append(message.text)
    next_index = current + 1

    await state.update_data(diagnostics_answers=answers, diagnostics_current=next_index)

    if next_index >= 7:
        # All diagnostics done — show profile
        await show_diagnostic_profile(message, state)
    else:
        # Next question
        thinking_types = [
            "analytical", "logical", "critical", "systemic",
            "strategic", "creative", "emotional",
        ]
        thinking_names = [
            "Аналитическое", "Логическое", "Критическое", "Системное",
            "Стратегическое", "Креативное", "Эмоциональный интеллект",
        ]
        data = await state.get_data()
        sphere = data.get("sphere", "общее развитие")

        thinking_msg = await message.answer(
            f"⏳ Готовлю вопрос #{next_index + 1}/7 ({thinking_names[next_index]})...",
        )

        from services.ai_service import ai_service

        question = await ai_service.get_diagnostic_question(
            sphere=sphere,
            thinking_type=thinking_types[next_index],
            question_number=next_index + 1,
            previous_answers=answers,
        )

        await thinking_msg.edit_text(question)

        state_names = [
            TrainerStates.diagnostics_q1, TrainerStates.diagnostics_q2,
            TrainerStates.diagnostics_q3, TrainerStates.diagnostics_q4,
            TrainerStates.diagnostics_q5, TrainerStates.diagnostics_q6,
            TrainerStates.diagnostics_q7,
        ]
        await state.set_state(state_names[next_index])


@router.message(TrainerStates.diagnostics_q7)
async def on_last_diagnostic_answer(message: Message, state: FSMContext) -> None:
    """Handle the last (7th) diagnostic answer."""
    if not message.text:
        await message.answer("Пожалуйста, напишите текстовый ответ.")
        return

    data = await state.get_data()
    answers: list[str] = data.get("diagnostics_answers", [])
    answers.append(message.text)

    await state.update_data(diagnostics_answers=answers)
    await show_diagnostic_profile(message, state)


async def show_diagnostic_profile(message: Message, state: FSMContext) -> None:
    """Generate and display the thinking profile after all 7 answers."""
    from bot.keyboards import thinking_type_keyboard
    from services.ai_service import ai_service

    data = await state.get_data()
    answers: list[str] = data.get("diagnostics_answers", [])
    sphere: str = data.get("sphere", "общее развитие")

    thinking_msg = await message.answer("⏳ Анализирую ваши ответы и составляю профиль мышления...")

    # Get profile from AI
    messages = ai_service.build_profile_prompt(answers, sphere)
    profile_text = await ai_service.chat(messages, temperature=0.7, max_tokens=2048)

    # Parse scores from AI response (rough extraction)
    scores = _parse_scores_from_text(profile_text)

    # Save initial scores to DB
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            for ttype, score in scores.items():
                await profile_service.update_score(session, user, ttype, score)

    # Store in FSM
    await state.update_data(current_scores=scores)

    await thinking_msg.edit_text(
        profile_text + "\n\n<b>С чего начнём тренировку?</b>",
        reply_markup=thinking_type_keyboard(current_scores=scores),
    )
    await state.set_state(TrainerStates.training_choice)


def _parse_scores_from_text(text: str) -> dict[str, int]:
    """Try to extract thinking type scores from AI-generated profile text."""
    import re

    type_map = {
        "аналитическое": "analytical",
        "логическое": "logical",
        "критическое": "critical",
        "системное": "systemic",
        "стратегическое": "strategic",
        "креативное": "creative",
        "эмоц": "emotional",
    }

    scores: dict[str, int] = {}
    for line in text.split("\n"):
        for name, key in type_map.items():
            if name.lower() in line.lower():
                match = re.search(r"(\d+)/10", line)
                if match:
                    scores[key] = int(match.group(1))
                break

    return scores
