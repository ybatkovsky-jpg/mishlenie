"""Handler for /book command — book-based learning mode with AI tutor."""

import asyncio
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import async_session_factory
from core.models import Book, BookProgress, BookSection, User
from services.ai_service import ai_service

logger = logging.getLogger(__name__)

router = Router()


class BookStates(StatesGroup):
    choosing_book = State()
    in_session = State()
    answering = State()
    feedback = State()


# --- Keyboard builders ---

def books_keyboard(books: list[Book], progress_map: dict[str, int]) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    type_emojis = {
        "critical": "🔍", "logical": "🧮", "analytical": "📊",
        "systemic": "🔗", "strategic": "🎯", "creative": "💡", "emotional": "❤️",
    }
    for book in books:
        emoji = type_emojis.get(book.thinking_type or "", "📖")
        progress = progress_map.get(book.id, 0)
        label = f"{emoji} {book.title[:50]} ({progress}/{book.section_count})"
        builder.add(InlineKeyboardButton(
            text=label,
            callback_data=f"book_{book.id}",
        ))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад к тренировке", callback_data="choose_type"))
    return builder.as_markup()


def session_keyboard() -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="▶️ Начать сессию", callback_data="book_start"))
    builder.add(InlineKeyboardButton(text="📊 Прогресс", callback_data="book_progress"))
    builder.add(InlineKeyboardButton(text="📖 Выбрать другую книгу", callback_data="book_list"))
    builder.adjust(1)
    return builder.as_markup()


def answer_keyboard() -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⏩ Пропустить главу", callback_data="book_skip"))
    builder.adjust(1)
    return builder.as_markup()


# --- Handlers ---

@router.message(Command("book"))
async def cmd_book(message: Message, state: FSMContext) -> None:
    """List available books for learning."""
    if not message.from_user:
        return

    async with async_session_factory() as session:
        # Get user
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Сначала выполните /start")
            return

        # Get all books
        result = await session.execute(
            select(Book).order_by(Book.thinking_type, Book.title)
        )
        books = list(result.scalars().all())

        if not books:
            await message.answer("📚 Книги ещё не загружены. Используйте /load_books.")
            return

        # Get progress for each book
        progress_map = {}
        for book in books:
            result = await session.execute(
                select(BookProgress).where(
                    BookProgress.user_id == user.id,
                    BookProgress.book_id == book.id,
                )
            )
            progress = result.scalar_one_or_none()
            progress_map[book.id] = progress.current_section if progress else 0

    await message.answer(
        "📚 <b>Выберите книгу для обучения:</b>\n\n"
        "Я проведу вас по главам: теория → примеры → вопросы → обратная связь.",
        reply_markup=books_keyboard(books, progress_map),
    )
    await state.set_state(BookStates.choosing_book)


@router.callback_query(BookStates.choosing_book, F.data.startswith("book_"))
async def on_book_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    """User selected a book — show progress and options."""
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

        # Get or create progress
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        result = await session.execute(
            select(BookProgress).where(
                BookProgress.user_id == user.id,
                BookProgress.book_id == book.id,
            )
        )
        progress = result.scalar_one_or_none()
        if not progress:
            progress = BookProgress(
                user_id=user.id,
                book_id=book.id,
                current_section=0,
                completed_sections="[]",
            )
            session.add(progress)
            await session.commit()

        current = progress.current_section
        total = book.section_count

    # Store in FSM
    await state.update_data(
        book_id=book_id,
        current_section=current,
    )

    sections_sorted = sorted(book.sections, key=lambda s: s.order_index)
    next_title = sections_sorted[current].title if current < total else "Завершено"

    await callback.message.edit_text(
        f"📖 <b>{book.title}</b>\n"
        f"✍️ {book.author or 'Автор неизвестен'}\n"
        f"🧠 Вид мышления: <b>{book.thinking_type or 'Общее'}</b>\n\n"
        f"📊 Прогресс: <b>{current}/{total}</b> глав\n"
        f"📌 Следующая: «{next_title}»",
        reply_markup=session_keyboard(),
    )
    await state.set_state(BookStates.in_session)


@router.callback_query(BookStates.in_session, F.data == "book_start")
async def on_start_session(callback: CallbackQuery, state: FSMContext) -> None:
    """Start a learning session for the current section."""
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
            await callback.message.answer("🎉 Вы прошли всю книгу! Поздравляю!")
            return

        section = sections[current]

    # Build prompt for AI tutor
    section_text = section.text[:8000]  # More context for better sessions
    user_msg = f"""Проведи обучающую сессию строго по тексту главы ниже. НЕ ИСПОЛЬЗУЙ свои общие знания об этой книге или авторе — работай ТОЛЬКО с предоставленным текстом.

Книга: {book.title}
Автор: {book.author or 'неизвестен'}
Вид мышления: {book.thinking_type or 'общее'}
Глава {current + 1} из {book.section_count}: {section.title}

=== ТЕКСТ ГЛАВЫ (единственный источник) ===
{section_text}
=== КОНЕЦ ТЕКСТА ===

Структура сессии: цели → теория → примеры → вопросы → кейс.
ВАЖНО: 
- Цитируй конкретные фразы из текста.
- Если какого-то понятия нет в тексте — не придумывай, скажи «в тексте главы это не раскрыто».
- Не ссылайся на другие главы или внешние источники.
- Ты НЕ знаешь эту книгу, ты видишь только текст выше."""

    await callback.message.answer("⏳ Готовлю сессию...")

    from prompts.book_tutor import BOOK_TUTOR_COMPACT
    messages = [
        {"role": "system", "content": BOOK_TUTOR_COMPACT},
        {"role": "user", "content": user_msg},
    ]

    response = await ai_service.chat(messages, temperature=0.5, max_tokens=3000)

    await callback.message.answer(response, reply_markup=answer_keyboard())
    await callback.message.answer("✍️ <b>Напишите ваш ответ</b> на вопросы и кейс выше. Или нажмите «Пропустить главу».")
    await state.set_state(BookStates.answering)


@router.callback_query(BookStates.answering, F.data == "book_skip")
async def on_skip_session(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip current section and move to next."""
    data = await state.get_data()
    book_id = data["book_id"]
    current = data["current_section"]

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        result = await session.execute(
            select(BookProgress).where(
                BookProgress.user_id == user.id,
                BookProgress.book_id == book_id,
            )
        )
        progress = result.scalar_one_or_none()

        if progress:
            completed = json.loads(progress.completed_sections or "[]")
            completed.append(current)
            progress.current_section = current + 1
            progress.completed_sections = json.dumps(completed)
            await session.commit()

    await state.update_data(current_section=current + 1)
    await on_start_session(callback, state)


@router.callback_query(BookStates.in_session, F.data == "book_list")
async def on_back_to_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to book list."""
    await cmd_book(callback.message, state)


@router.message(BookStates.answering)
async def on_book_answer(message: Message, state: FSMContext) -> None:
    """User answers questions from the book session."""
    if not message.text or not message.from_user:
        return

    data = await state.get_data()
    book_id = data["book_id"]
    current = data["current_section"]

    async with async_session_factory() as session:
        result = await session.execute(
            select(Book).where(Book.id == book_id).options(selectinload(Book.sections))
        )
        book = result.scalar_one_or_none()
        if not book:
            return

        sections = sorted(book.sections, key=lambda s: s.order_index)
        section = sections[current] if current < len(sections) else None

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        # Get AI feedback on answers
        from prompts.book_tutor import BOOK_TUTOR_COMPACT

        section_title = section.title if section else ""
        feedback_msg_text = f"""Пользователь ответил на вопросы по главе «{section_title}» книги «{book.title}».

Ответ пользователя:
{message.text[:2000]}

Дай развёрнутую обратную связь:
- Что правильно
- Какие неточности
- Как улучшить понимание
- Оценка понимания (1-10)
- Предложи перечитать конкретный раздел, если нужно."""

        await message.answer("⏳ Проверяю ответы...")

        messages = [
            {"role": "system", "content": BOOK_TUTOR_COMPACT},
            {"role": "user", "content": feedback_msg_text},
        ]

        feedback = await ai_service.chat(messages, temperature=0.5, max_tokens=1536)

        # Move to next section
        result = await session.execute(
            select(BookProgress).where(
                BookProgress.user_id == user.id,
                BookProgress.book_id == book_id,
            )
        )
        progress = result.scalar_one_or_none()
        if progress:
            completed = json.loads(progress.completed_sections or "[]")
            completed.append(current)
            progress.current_section = current + 1
            progress.completed_sections = json.dumps(completed)
            await session.commit()

    await state.update_data(current_section=current + 1)
    await message.answer(feedback, reply_markup=session_keyboard())
    await state.set_state(BookStates.in_session)


@router.callback_query(F.data == "book_progress")
async def on_show_book_progress(callback: CallbackQuery, state: FSMContext) -> None:
    """Show detailed progress for current book."""
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

        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        result = await session.execute(
            select(BookProgress).where(
                BookProgress.user_id == user.id,
                BookProgress.book_id == book_id,
            )
        )
        progress = result.scalar_one_or_none()
        completed = json.loads(progress.completed_sections) if progress and progress.completed_sections else []

    sections = sorted(book.sections, key=lambda s: s.order_index)
    lines = [f"📖 <b>{book.title}</b>\n"]
    for i, s in enumerate(sections):
        status = "✅" if i in completed else "⬜" if i > (progress.current_section if progress else 0) else "🔄"
        lines.append(f"{status} Гл.{i+1}: {s.title[:60]}")

    await callback.message.answer("\n".join(lines), reply_markup=session_keyboard())
    await callback.answer()
