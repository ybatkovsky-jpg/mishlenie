"""Handler for /book command — conversational book learning with AI tutor."""

import asyncio
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import async_session_factory
from core.models import Book, BookProgress, BookSection, User
from services.ai_service import ai_service

logger = logging.getLogger(__name__)

router = Router()


class BookStates(StatesGroup):
    choosing_book = State()
    in_dialogue = State()  # Main conversational state


TYPE_EMOJIS = {
    "critical": "🔍", "logical": "🧮", "analytical": "📊",
    "systemic": "🔗", "strategic": "🎯", "creative": "💡", "emotional": "❤️",
}


# ──── Keyboards ────

def books_keyboard(books: list[Book], progress_map: dict[str, int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for book in books:
        emoji = TYPE_EMOJIS.get(book.thinking_type or "", "📖")
        progress = progress_map.get(book.id, 0)
        label = f"{emoji} {book.title[:50]} ({progress}/{book.section_count})"
        builder.add(InlineKeyboardButton(text=label, callback_data=f"book_{book.id}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Вернуться к тренировке", callback_data="choose_type"))
    return builder.as_markup()


def dialogue_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="❓ Задать вопрос по тексту", callback_data="dial_ask"),
        InlineKeyboardButton(text="💡 Попросить пример", callback_data="dial_example"),
    )
    builder.add(
        InlineKeyboardButton(text="🧪 Дать кейс / задачу", callback_data="dial_case"),
        InlineKeyboardButton(text="📝 Проверить понимание", callback_data="dial_check"),
    )
    builder.add(
        InlineKeyboardButton(text="▶️ Следующая глава", callback_data="dial_next"),
    )
    builder.add(
        InlineKeyboardButton(text="📖 Выбрать другую книгу", callback_data="book_list"),
    )
    builder.adjust(2)
    return builder.as_markup()


# ──── /book — show book list ────

@router.message(Command("book"))
async def cmd_book(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Сначала выполните /start")
            return

        result = await session.execute(select(Book).order_by(Book.thinking_type, Book.title))
        books = list(result.scalars().all())

        if not books:
            await message.answer("📚 Книги ещё не загружены.")
            return

        progress_map = {}
        for book in books:
            result = await session.execute(
                select(BookProgress).where(BookProgress.user_id == user.id, BookProgress.book_id == book.id)
            )
            p = result.scalar_one_or_none()
            progress_map[book.id] = p.current_section if p else 0

    await message.answer(
        "📚 <b>Выберите книгу для обучения:</b>",
        reply_markup=books_keyboard(books, progress_map),
    )
    await state.set_state(BookStates.choosing_book)


# ──── Book chosen → show info + start ────

@router.callback_query(BookStates.choosing_book, F.data.startswith("book_"))
async def on_book_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.from_user:
        return

    book_id = callback.data.replace("book_", "")

    async with async_session_factory() as session:
        result = await session.execute(
            select(Book).where(Book.id == book_id).options(selectinload(Book.sections))
        )
        book = result.scalar_one_or_none()
        if not book:
            await callback.answer("Книга не найдена")
            return

        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        result = await session.execute(
            select(BookProgress).where(BookProgress.user_id == user.id, BookProgress.book_id == book.id)
        )
        progress = result.scalar_one_or_none()
        if not progress:
            progress = BookProgress(user_id=user.id, book_id=book.id, current_section=0, completed_sections="[]")
            session.add(progress)
            await session.commit()

        current = progress.current_section
        total = book.section_count

    sections = sorted(book.sections, key=lambda s: s.order_index)
    next_title = sections[current].title if current < total else "Завершено"

    await state.update_data(book_id=book_id, current_section=current, dialogue_history=[])

    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="▶️ Начать сессию", callback_data="dial_start"),
        InlineKeyboardButton(text="📊 Прогресс", callback_data="book_progress_dial"),
    )
    builder.adjust(1)

    await callback.message.edit_text(
        f"📖 <b>{book.title}</b>\n"
        f"✍️ {book.author or 'Автор неизвестен'}\n"
        f"🧠 Вид мышления: <b>{book.thinking_type or 'Общее'}</b>\n\n"
        f"📊 Прогресс: <b>{current}/{total}</b> глав\n"
        f"📌 Следующая: «{next_title}»",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(BookStates.in_dialogue)


# ──── Start session: show chapter content ────

@router.callback_query(BookStates.in_dialogue, F.data == "dial_start")
async def on_start_dialogue(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    book_id = data["book_id"]
    current = data["current_section"]

    async with async_session_factory() as session:
        result = await session.execute(
            select(Book).where(Book.id == book_id).options(selectinload(Book.sections))
        )
        book = result.scalar_one_or_none()
        if not book:
            await callback.answer("Книга не найдена")
            return

        sections = sorted(book.sections, key=lambda s: s.order_index)
        if current >= len(sections):
            await callback.message.answer("🎉 Вы прошли всю книгу!")
            return

        section = sections[current]

    section_text = section.text[:8000]

    # Save section context for the dialogue
    await state.update_data(
        section_title=section.title,
        section_text=section_text,
        dialogue_history=[],
    )

    prompt = f"""Ты — сократический тьютор. Представь главу книги так, чтобы пользователь захотел с тобой это обсудить.

Книга: {book.title}
Глава {current + 1}/{book.section_count}: {section.title}
Вид мышления: {book.thinking_type or 'общее'}

=== ТЕКСТ ГЛАВЫ ===
{section_text}
=== КОНЕЦ ===

Сделай следующее:
1. Кратко изложи 2-3 ключевые идеи главы (своими словами, но ТОЛЬКО на основе текста).
2. Приведи 1 яркий пример из текста.
3. Закончи ОДНИМ открытым вопросом к пользователю — чтобы начать обсуждение.

Правила:
- НЕ используй Markdown (**, ###, #).
- Будь живым собеседником, а не лектором.
- Ты НЕ знаешь книгу — только текст выше.
- Ответь коротко (до 250 слов) — оставь место для диалога."""

    await callback.message.answer("⏳ Читаю главу...")

    from prompts.book_tutor import BOOK_TUTOR_COMPACT

    messages = [
        {"role": "system", "content": BOOK_TUTOR_COMPACT},
        {"role": "user", "content": prompt},
    ]

    response = await ai_service.chat(messages, temperature=0.6, max_tokens=2000)

    await state.update_data(dialogue_history=[
        {"role": "assistant", "content": response},
    ])

    await callback.message.answer(response, reply_markup=dialogue_keyboard())


# ──── Dialogue: user asks a question ────

@router.callback_query(BookStates.in_dialogue, F.data == "dial_ask")
async def on_dial_ask(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "✍️ <b>Задайте вопрос по тексту главы.</b>\n"
        "Можете спросить про любое понятие, термин или идею — я объясню, опираясь только на текст."
    )
    await callback.answer()


# ──── Dialogue: user wants an example ────

@router.callback_query(BookStates.in_dialogue, F.data == "dial_example")
async def on_dial_example(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    section_text = data.get("section_text", "")
    section_title = data.get("section_title", "")

    prompt = f"""Пользователь просит дополнительный пример по главе «{section_title}».

=== ТЕКСТ ГЛАВЫ ===
{section_text[:6000]}
=== КОНЕЦ ===

Придумай 1-2 ПРАКТИЧЕСКИХ примера из жизни/работы, иллюстрирующих ключевые идеи главы.
Примеры должны быть ТВОИМИ (с пометкой «Пример от тьютора»), но основанными на концепциях из текста.
НЕ используй Markdown. Будь конкретным."""

    await callback.message.answer("⏳ Придумываю примеры...")

    messages = [
        {"role": "system", "content": "Ты — ИИ-тьютор. Отвечай на русском, без Markdown."},
        {"role": "user", "content": prompt},
    ]
    response = await ai_service.chat(messages, temperature=0.7, max_tokens=1500)

    history: list = data.get("dialogue_history", [])
    history.append({"role": "assistant", "content": response})
    await state.update_data(dialogue_history=history)

    await callback.message.answer(response, reply_markup=dialogue_keyboard())
    await callback.answer()


# ──── Dialogue: user wants a case / exercise ────

@router.callback_query(BookStates.in_dialogue, F.data == "dial_case")
async def on_dial_case(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    section_text = data.get("section_text", "")
    section_title = data.get("section_title", "")

    prompt = f"""Пользователь просит практический кейс или задачу по главе «{section_title}».

=== ТЕКСТ ГЛАВЫ ===
{section_text[:6000]}
=== КОНЕЦ ===

Придумай ОДИН практический кейс (реалистичную ситуацию), где нужно применить идеи из главы.
Опиши ситуацию и задай 2-3 вопроса, которые заставят пользователя применить концепции из текста.
НЕ давай ответы сразу — сначала пусть пользователь подумает.
НЕ используй Markdown."""

    await callback.message.answer("⏳ Готовлю кейс...")

    messages = [
        {"role": "system", "content": "Ты — ИИ-тьютор. Отвечай на русском, без Markdown."},
        {"role": "user", "content": prompt},
    ]
    response = await ai_service.chat(messages, temperature=0.7, max_tokens=1500)

    history: list = data.get("dialogue_history", [])
    history.append({"role": "assistant", "content": response})
    await state.update_data(dialogue_history=history)

    await callback.message.answer(response, reply_markup=dialogue_keyboard())
    await callback.answer()


# ──── Dialogue: check understanding ────

@router.callback_query(BookStates.in_dialogue, F.data == "dial_check")
async def on_dial_check(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    section_text = data.get("section_text", "")
    section_title = data.get("section_title", "")

    prompt = f"""Пользователь хочет проверить своё понимание главы «{section_title}».

=== ТЕКСТ ГЛАВЫ ===
{section_text[:6000]}
=== КОНЕЦ ===

Задай 3 открытых вопроса, проверяющих ГЛУБОКОЕ понимание материала (не просто пересказ, а применение и анализ).
НЕ используй Markdown."""

    await callback.message.answer("⏳ Готовлю проверочные вопросы...")

    messages = [
        {"role": "system", "content": "Ты — ИИ-тьютор. Отвечай на русском, без Markdown."},
        {"role": "user", "content": prompt},
    ]
    response = await ai_service.chat(messages, temperature=0.7, max_tokens=1000)

    history: list = data.get("dialogue_history", [])
    history.append({"role": "assistant", "content": response})
    await state.update_data(dialogue_history=history)

    await callback.message.answer(response, reply_markup=dialogue_keyboard())
    await callback.answer()


# ──── Dialogue: next chapter ────

@router.callback_query(BookStates.in_dialogue, F.data == "dial_next")
async def on_dial_next(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    book_id = data["book_id"]
    current = data["current_section"]

    # Save progress
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        result = await session.execute(
            select(BookProgress).where(BookProgress.user_id == user.id, BookProgress.book_id == book_id)
        )
        progress = result.scalar_one_or_none()
        if progress:
            completed = json.loads(progress.completed_sections or "[]")
            if current not in completed:
                completed.append(current)
            progress.current_section = current + 1
            progress.completed_sections = json.dumps(completed)
            await session.commit()

        # Check if book finished
        result = await session.execute(
            select(Book).where(Book.id == book_id)
        )
        book = result.scalar_one_or_none()
        total = book.section_count if book else 0

    new_current = current + 1

    if new_current >= total:
        await callback.message.answer(
            f"🎉 <b>Поздравляю! Вы прошли всю книгу «{book.title if book else ''}»!</b>\n\n"
            f"Что дальше?",
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="📖 Выбрать другую книгу", callback_data="book_list")
            ).as_markup(),
        )
        return

    await state.update_data(current_section=new_current, dialogue_history=[])

    # Show next chapter preview
    async with async_session_factory() as session:
        result = await session.execute(
            select(Book).where(Book.id == book_id).options(selectinload(Book.sections))
        )
        book = result.scalar_one_or_none()
        if not book:
            return
        sections = sorted(book.sections, key=lambda s: s.order_index)
        next_section = sections[new_current]

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="▶️ Начать следующую главу", callback_data="dial_start"))
    builder.add(InlineKeyboardButton(text="📖 Выбрать другую книгу", callback_data="book_list"))
    builder.adjust(1)

    await callback.message.answer(
        f"✅ Глава {current + 1} пройдена.\n\n"
        f"📌 <b>Следующая: «{next_section.title}»</b>\n"
        f"📊 Прогресс: {new_current}/{total}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ──── Handle ANY user text in dialogue mode ────

@router.message(BookStates.in_dialogue)
async def on_dialogue_message(message: Message, state: FSMContext) -> None:
    """Any text message in dialogue state is sent to the AI tutor."""
    if not message.text or not message.from_user:
        return

    data = await state.get_data()
    section_text = data.get("section_text", "")
    section_title = data.get("section_title", "")
    dialogue_history: list = data.get("dialogue_history", [])

    # Build conversation context
    from prompts.book_tutor import BOOK_TUTOR_COMPACT

    history_str = ""
    for entry in dialogue_history[-6:]:  # Last 6 exchanges
        role = "Тьютор" if entry["role"] == "assistant" else "Студент"
        history_str += f"{role}: {entry['content'][:500]}\n"

    prompt = f"""Идёт обсуждение главы «{section_title}».

=== ТЕКСТ ГЛАВЫ (для справки) ===
{section_text[:6000]}
=== КОНЕЦ ===

История диалога:
{history_str}

Студент написал:
{message.text[:2000]}

Ответь как тьютор:
- Ответь на вопрос/комментарий студента.
- Если студент ошибается — мягко поправь, ссылаясь на текст.
- Если студент просит объяснить — объясни глубже, но ТОЛЬКО на основе текста главы.
- Поощряй дальнейшее обсуждение: задай встречный вопрос.
- Будь конкретным, цитируй текст где уместно.
- НЕ используй Markdown."""

    await message.answer("⏳ Думаю...")

    messages = [
        {"role": "system", "content": BOOK_TUTOR_COMPACT},
        {"role": "user", "content": prompt},
    ]
    response = await ai_service.chat(messages, temperature=0.6, max_tokens=2000)

    dialogue_history.append({"role": "user", "content": message.text})
    dialogue_history.append({"role": "assistant", "content": response})
    await state.update_data(dialogue_history=dialogue_history)

    await message.answer(response, reply_markup=dialogue_keyboard())


# ──── Handlers for navigation between states ────

@router.callback_query(F.data == "book_list")
async def on_back_to_list(callback: CallbackQuery, state: FSMContext) -> None:
    await cmd_book(callback.message, state)
    await callback.answer()


@router.callback_query(BookStates.in_dialogue, F.data == "book_progress_dial")
async def on_show_progress(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    book_id = data.get("book_id")
    if not book_id:
        await callback.answer("Сначала выберите книгу")
        return

    async with async_session_factory() as session:
        result = await session.execute(
            select(Book).where(Book.id == book_id).options(selectinload(Book.sections))
        )
        book = result.scalar_one_or_none()
        if not book:
            await callback.answer("Книга не найдена")
            return

        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        result = await session.execute(
            select(BookProgress).where(BookProgress.user_id == user.id, BookProgress.book_id == book.id)
        )
        progress = result.scalar_one_or_none()
        completed = json.loads(progress.completed_sections) if progress and progress.completed_sections else []
        cur = progress.current_section if progress else 0

    sections = sorted(book.sections, key=lambda s: s.order_index)
    lines = [f"📖 <b>{book.title}</b>\n"]
    for i, s in enumerate(sections):
        if i < cur:
            status = "✅"
        elif i in completed:
            status = "✅"
        elif i == cur:
            status = "🔄"
        else:
            status = "⬜"
        lines.append(f"{status} Гл.{i+1}: {s.title[:60]}")

    await callback.message.answer("\n".join(lines))
    await callback.answer()
