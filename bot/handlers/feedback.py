"""Handler for Phase 3: Feedback — analyze user's answer and provide feedback."""

import json
import logging
import random
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards import after_feedback_keyboard, thinking_type_keyboard
from bot.states import TrainerStates
from core.database import async_session_factory
from core.models import User, ReviewItem
from services.ai_service import ai_service
from services.profile_service import profile_service
from services.progress_service import progress_service

logger = logging.getLogger(__name__)

router = Router()

# Complementary thinking types for interleaving suggestions
COMPLEMENTARY_TYPES = {
    "analytical": ["systemic", "critical"],
    "logical": ["critical", "analytical"],
    "critical": ["logical", "strategic"],
    "systemic": ["analytical", "strategic"],
    "strategic": ["systemic", "creative"],
    "creative": ["strategic", "emotional"],
    "emotional": ["creative", "critical"],
}


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
        user_id=str(message.from_user.id),
    )

    # Extract score from feedback text
    score = _extract_score(feedback_text)

    # Extract error type if present
    error_type = _extract_error_type(feedback_text)
    # Strip the ERROR_TYPE marker from displayed feedback
    feedback_text = _strip_error_marker(feedback_text)

    # Record error pattern if found
    if error_type and thinking_type != "combined":
        try:
            from services.error_analyzer import error_analyzer_service
            async with async_session_factory() as s:
                u_result = await s.execute(
                    select(User).where(User.telegram_id == message.from_user.id)
                )
                u = u_result.scalar_one_or_none()
                if u:
                    await error_analyzer_service.record_error(s, u, error_type, thinking_type)
        except Exception:
            logger.warning("Failed to record error pattern", exc_info=True)

    # Track difficulty history for adaptive difficulty
    difficulty_history: list[int] = data.get("difficulty_history", [])
    difficulty = data.get("difficulty", 0)
    old_difficulty = difficulty

    if score is not None:
        difficulty_history.append(score)
        if len(difficulty_history) > 5:
            difficulty_history = difficulty_history[-5:]

        # Adaptive difficulty: last 2 scores drive level changes
        if len(difficulty_history) >= 2:
            last_two = difficulty_history[-2:]
            if all(s >= 8 for s in last_two):
                difficulty = min(2, difficulty + 1)
            elif all(s <= 4 for s in last_two):
                difficulty = max(0, difficulty - 1)

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
                prompt_version=f"feedback_{_get_variant(str(message.from_user.id))}",
                error_type=error_type,
            )

            # Update thinking profile with new score (cumulative scoring)
            level_changed = None
            if score and thinking_type != "combined":
                current_scores = data.get("current_scores", {})
                current_scores[thinking_type] = score
                level_changed = await profile_service.update_score(session, user, thinking_type, score)
                await state.update_data(current_scores=current_scores)

            # Get stats for combined eligibility
            stats = await progress_service.get_stats(session, user)
            show_combined = stats["types_completed"] >= 3

            # Interleaving suggestion: after 2+ consecutive same-type, suggest switch
            consecutive = await progress_service.get_consecutive_same_type(
                session, user, thinking_type
            )
            suggest_interleaving = consecutive >= 2 and thinking_type != "combined"
            suggest_type = None
            if suggest_interleaving and thinking_type in COMPLEMENTARY_TYPES:
                candidates = [t for t in COMPLEMENTARY_TYPES[thinking_type]
                             if t in stats["completed_type_names"]]
                if not candidates:
                    candidates = [t for t in COMPLEMENTARY_TYPES[thinking_type]]
                suggest_type = random.choice(candidates)

    # Save updated difficulty to FSM
    await state.update_data(
        difficulty=difficulty,
        difficulty_history=difficulty_history,
    )

    # Show feedback to user
    await feedback_msg.edit_text(feedback_text)

    # Schedule spaced repetition for this task's concepts
    if score is not None and thinking_type != "combined":
        try:
            from services.spaced_repetition import spaced_repetition_service
            from services.ai_service import ai_service as ai_svc

            # Extract key concepts from the task
            concepts_prompt = f"""Из этого задания выдели 2-3 ключевых концепта (одно-два слова каждый) в виде JSON-массива строк.
Задание: {task_text[:800]}
Верни ТОЛЬКО JSON-массив, например: ["декомпозиция", "причинный анализ"]. Без Markdown."""
            concepts_response = await ai_svc.chat(
                [{"role": "user", "content": concepts_prompt}],
                temperature=0.3, max_tokens=200,
            )
            try:
                concepts = json.loads(concepts_response.strip().removeprefix("```json").removesuffix("```").strip())
                if isinstance(concepts, list) and len(concepts) > 0:
                    async with async_session_factory() as s:
                        result = await s.execute(
                            select(User).where(User.telegram_id == message.from_user.id)
                        )
                        u = result.scalar_one_or_none()
                        if u:
                            await spaced_repetition_service.schedule_review(
                                s, u, thinking_type,
                                concept_keywords=concepts[:3],
                                task_summary=task_text[:300],
                            )
            except (json.JSONDecodeError, ValueError):
                pass  # If AI doesn't return valid JSON, skip scheduling
        except Exception:
            logger.warning("Failed to schedule spaced repetition", exc_info=True)

    # Announce difficulty change
    if difficulty > old_difficulty:
        await message.answer("🔼 Сложность повышена! Задания станут более комплексными.")
    elif difficulty < old_difficulty:
        await message.answer("🔽 Сложность понижена — вернёмся к более простым сценариям.")

    # Complete spaced repetition reviews if this was a review task
    review_ids = data.get("review_item_ids", [])
    if review_ids and thinking_type == "review":
        try:
            from services.spaced_repetition import spaced_repetition_service
            async with async_session_factory() as s:
                for rid in review_ids:
                    result = await s.execute(select(ReviewItem).where(ReviewItem.id == rid))
                    item = result.scalar_one_or_none()
                    if item:
                        passed = score is not None and score >= 5
                        await spaced_repetition_service.complete_review(s, item, passed=passed)
                await message.answer(f"✅ {len(review_ids)} концептов освежено в памяти!")
        except Exception:
            logger.warning("Failed to complete review items", exc_info=True)
        finally:
            await state.update_data(review_item_ids=[])

    # Announce level change
    if level_changed:
        level_names = {"novice": "🌱 Новичок", "practitioner": "🌿 Практик", "master": "🌳 Мастер", "expert": "👑 Эксперт"}
        await message.answer(
            f"🎉 Новый уровень: <b>{level_names.get(level_changed, level_changed)}</b> "
            f"в виде мышления «{_type_name(thinking_type)}»!"
        )

    # Show next action keyboard
    # Check if retrieval practice check-in is needed (every 3 exercises of same type)
    need_checkin = False
    if thinking_type != "combined" and score is not None:
        async with async_session_factory() as s:
            u_result = await s.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            u = u_result.scalar_one_or_none()
            if u:
                type_count = await progress_service.get_type_exercise_count(s, u, thinking_type)
                # Check-in every 3 exercises of the same type
                need_checkin = type_count > 0 and type_count % 3 == 0

    if need_checkin:
        await message.answer(
            f"🧠 <b>Пауза на вспоминание</b>\n\n"
            f"Вы выполнили несколько заданий по виду мышления «{_type_name(thinking_type)}».\n"
            f"Какие 2-3 ключевых принципа или идеи вы запомнили? "
            f"Чему вы научились за эти задания?\n\n"
            f"<i>Это помогает закрепить знания — просто напишите своими словами.</i>"
        )
        await state.set_state(TrainerStates.retrieval_checkin)
    else:
        await message.answer(
            "👇 <b>Что дальше?</b>",
            reply_markup=after_feedback_keyboard(
                thinking_type=thinking_type,
                show_combined=show_combined,
                suggest_interleaving=suggest_interleaving,
                suggest_type=suggest_type,
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


# ──── Difficulty control buttons ────

@router.callback_query(TrainerStates.feedback_view, F.data == "diff_easier")
async def on_diff_easier(callback: CallbackQuery, state: FSMContext) -> None:
    """User wants easier tasks."""
    data = await state.get_data()
    difficulty = max(0, data.get("difficulty", 0) - 1)
    await state.update_data(difficulty=difficulty)
    await callback.answer("🔽 Сложность понижена")
    # Auto-generate next task at new difficulty
    await _start_next_with_difficulty(callback, state, difficulty)


@router.callback_query(TrainerStates.feedback_view, F.data == "diff_harder")
async def on_diff_harder(callback: CallbackQuery, state: FSMContext) -> None:
    """User wants harder tasks."""
    data = await state.get_data()
    difficulty = min(2, data.get("difficulty", 0) + 1)
    await state.update_data(difficulty=difficulty)
    await callback.answer("🔼 Сложность повышена")
    await _start_next_with_difficulty(callback, state, difficulty)


# ──── Random type (interleaving) handler ────

@router.callback_query(F.data == "type_random")
async def on_random_type(callback: CallbackQuery, state: FSMContext) -> None:
    """User chose random thinking type for interleaving practice."""
    data = await state.get_data()
    sphere = data.get("sphere", "общее развитие")
    difficulty = data.get("difficulty", 0)

    # Pick a random type that isn't the current one
    all_types = ["analytical", "logical", "critical", "systemic", "strategic", "creative", "emotional"]
    current = data.get("current_thinking_type", "")
    candidates = [t for t in all_types if t != current] if current else all_types
    thinking_type = random.choice(candidates)

    await state.update_data(current_thinking_type=thinking_type)

    await callback.message.answer(
        f"🎲 Случайный выбор: <b>{_type_name(thinking_type)}</b>\n"
        f"⏳ Готовлю задание..."
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


async def _start_next_with_difficulty(callback: CallbackQuery, state: FSMContext, difficulty: int) -> None:
    """Generate next task at specified difficulty level."""
    data = await state.get_data()
    thinking_type = data.get("current_thinking_type", "analytical")
    sphere = data.get("sphere", "общее развитие")

    task_text = await ai_service.get_training_task(
        thinking_type=thinking_type,
        sphere=sphere,
        difficulty=difficulty,
        use_reasoner=False,
    )

    await state.update_data(current_task=task_text)
    await callback.message.answer(task_text, reply_markup=_continue_keyboard())
    await state.set_state(TrainerStates.training_task)


# ──── Retrieval Practice check-in handler ────

@router.message(TrainerStates.retrieval_checkin)
async def on_retrieval_checkin(message: Message, state: FSMContext) -> None:
    """User responded to a retrieval practice check-in — give gentle feedback."""
    if not message.text or not message.from_user:
        await message.answer("Пожалуйста, напишите текстовый ответ.")
        return

    data = await state.get_data()
    thinking_type = data.get("current_thinking_type", "analytical")

    # AI gives a brief analysis of how well the user recalled key principles
    check_prompt = f"""Пользователь прошёл несколько заданий по виду мышления: {thinking_type}.
На вопрос «Какие ключевые принципы вы запомнили?» он ответил:
{message.text[:1000]}

Дай КОРОТКУЮ обратную связь (2-3 предложения):
- Отметь, что пользователь вспомнил правильно
- Если что-то важное упущено — мягко напомни 1 ключевой принцип
- Подбодри (это упражнение на вспоминание, а не на оценку)
НЕ используй Markdown."""

    from prompts.system_prompt import SYSTEM_PROMPT_COMPACT
    response = await ai_service.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT_COMPACT},
            {"role": "user", "content": check_prompt},
        ],
        temperature=0.5, max_tokens=600,
    )

    await message.answer(response)

    # Now show the normal next-action menu
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            stats = await progress_service.get_stats(session, user)
            show_combined = stats["types_completed"] >= 3
            consecutive = await progress_service.get_consecutive_same_type(
                session, user, thinking_type
            )
            suggest_interleaving = consecutive >= 2 and thinking_type != "combined"
            suggest_type = None
            if suggest_interleaving and thinking_type in COMPLEMENTARY_TYPES:
                candidates = [t for t in COMPLEMENTARY_TYPES[thinking_type]
                             if t in stats["completed_type_names"]]
                if not candidates:
                    candidates = [t for t in COMPLEMENTARY_TYPES[thinking_type]]
                suggest_type = random.choice(candidates)
        else:
            show_combined = False
            suggest_interleaving = False
            suggest_type = None

    await message.answer(
        "👇 <b>Что дальше?</b>",
        reply_markup=after_feedback_keyboard(
            thinking_type=thinking_type,
            show_combined=show_combined,
            suggest_interleaving=suggest_interleaving,
            suggest_type=suggest_type,
        ),
    )
    await state.set_state(TrainerStates.feedback_view)
    """Generate next task at specified difficulty level."""
    data = await state.get_data()
    thinking_type = data.get("current_thinking_type", "analytical")
    sphere = data.get("sphere", "общее развитие")

    task_text = await ai_service.get_training_task(
        thinking_type=thinking_type,
        sphere=sphere,
        difficulty=difficulty,
        use_reasoner=False,
    )

    await state.update_data(current_task=task_text)
    await callback.message.answer(task_text, reply_markup=_continue_keyboard())
    await state.set_state(TrainerStates.training_task)


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


def _extract_error_type(text: str) -> str | None:
    """Extract error type from AI feedback like '[ERROR_TYPE: confirmation_bias]'."""
    match = re.search(r"\[ERROR_TYPE:\s*(\w+)\]", text)
    if match:
        error_type = match.group(1).strip()
        if error_type != "none":
            return error_type
    return None


def _strip_error_marker(text: str) -> str:
    """Remove [ERROR_TYPE: ...] marker from displayed text."""
    return re.sub(r"\s*\[ERROR_TYPE:\s*\w+\]\s*", "", text).strip()


def _get_variant(user_id: str) -> str:
    """Get A/B variant for a user (deterministic)."""
    from services.ab_analyzer import ab_analyzer_service
    return ab_analyzer_service.get_variant(user_id, "feedback")


def _continue_keyboard():
    from bot.keyboards import continue_keyboard
    return continue_keyboard()


def _type_name(key: str) -> str:
    from prompts.templates import get_thinking_type_name
    return get_thinking_type_name(key)
