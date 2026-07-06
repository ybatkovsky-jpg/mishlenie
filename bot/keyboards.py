"""Inline keyboards for the trainer bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from prompts.templates import THINKING_TYPES


def sphere_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting application sphere."""
    builder = InlineKeyboardBuilder()
    spheres = [
        ("💼 Работа", "sphere_работа"),
        ("🚀 Бизнес", "sphere_бизнес"),
        ("📚 Учёба", "sphere_учёба"),
        ("❤️ Отношения", "sphere_отношения"),
        ("💭 Личные решения", "sphere_личные решения"),
        ("🌟 Общее развитие", "sphere_общее развитие"),
    ]
    for label, callback in spheres:
        builder.add(InlineKeyboardButton(text=label, callback_data=callback))
    builder.adjust(2)
    return builder.as_markup()


def thinking_type_keyboard(
    show_combined: bool = False,
    current_scores: dict[str, int] | None = None,
    current_trends: dict[str, str] | None = None,
    show_random: bool = True,
) -> InlineKeyboardMarkup:
    """Keyboard for selecting a thinking type to train.

    Args:
        show_combined: Whether to show the "combined task" button.
        current_scores: Current scores to display next to type names.
        current_trends: Trend indicators (↑/↓/→) for each type.
        show_random: Whether to show "random type" button for interleaving.
    """
    builder = InlineKeyboardBuilder()
    type_names = [
        ("📊 Аналитическое", "type_analytical"),
        ("🧮 Логическое", "type_logical"),
        ("🔍 Критическое", "type_critical"),
        ("🔗 Системное", "type_systemic"),
        ("🎯 Стратегическое", "type_strategic"),
        ("💡 Креативное", "type_creative"),
        ("❤️ Эмоц. интеллект", "type_emotional"),
    ]
    for label, callback in type_names:
        key = callback.replace("type_", "")
        parts = [label]
        if current_scores and key in current_scores:
            parts.append(f" {current_scores[key]}/10")
        if current_trends and key in current_trends and current_trends[key]:
            parts.append(f" {current_trends[key]}")
        builder.add(InlineKeyboardButton(text="".join(parts), callback_data=callback))

    builder.adjust(2)

    if show_combined:
        builder.row(
            InlineKeyboardButton(
                text="🔄 Комбинированное задание",
                callback_data="type_combined",
            )
        )

    if show_random:
        builder.row(
            InlineKeyboardButton(text="🎲 Случайный тип", callback_data="type_random"),
        )

    builder.row(
        InlineKeyboardButton(text="🧘 Упражнение на осознанность", callback_data="mindfulness"),
    )
    builder.row(
        InlineKeyboardButton(text="🧠 Мой профиль", callback_data="profile"),
    )

    return builder.as_markup()


def difficulty_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting difficulty (if user wants to change it)."""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🟢 Начальный (быт)", callback_data="diff_0"),
        InlineKeyboardButton(text="🟡 Средний (работа)", callback_data="diff_1"),
        InlineKeyboardButton(text="🔴 Продвинутый (абстрактный)", callback_data="diff_2"),
    )
    builder.adjust(1)
    return builder.as_markup()


def continue_keyboard() -> InlineKeyboardMarkup:
    """Simple 'continue' button."""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="▶️ Продолжить", callback_data="continue"),
        InlineKeyboardButton(text="🧘 Осознанная пауза", callback_data="mindfulness"),
    )
    builder.adjust(1)
    return builder.as_markup()


def after_feedback_keyboard(
    thinking_type: str | None = None,
    show_combined: bool = False,
    suggest_interleaving: bool = False,
    suggest_type: str | None = None,
) -> InlineKeyboardMarkup:
    """Keyboard shown after feedback — choose next action."""
    builder = InlineKeyboardBuilder()

    if suggest_interleaving and suggest_type:
        from prompts.templates import get_thinking_type_name
        type_name = get_thinking_type_name(suggest_type)
        builder.add(
            InlineKeyboardButton(
                text=f"🔀 Попробовать: {type_name} (рекомендуется)",
                callback_data=f"type_{suggest_type}",
            )
        )

    builder.add(
        InlineKeyboardButton(text="📝 Следующее задание (тот же вид)", callback_data="next_same"),
        InlineKeyboardButton(text="🎯 Выбрать другой вид", callback_data="choose_type"),
    )
    if show_combined:
        builder.add(
            InlineKeyboardButton(
                text="🔄 Комбинированное задание",
                callback_data="type_combined",
            )
        )
    builder.add(
        InlineKeyboardButton(text="🧘 Осознанная пауза", callback_data="mindfulness"),
    )
    # Difficulty control buttons
    builder.row(
        InlineKeyboardButton(text="🔽 Проще", callback_data="diff_easier"),
        InlineKeyboardButton(text="🔼 Сложнее", callback_data="diff_harder"),
    )
    builder.adjust(1)
    return builder.as_markup()


def mindfulness_choice_keyboard() -> InlineKeyboardMarkup:
    """After mindfulness exercise — what next?"""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🎯 К заданиям", callback_data="choose_type"),
        InlineKeyboardButton(text="🧠 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
    )
    builder.adjust(2)
    return builder.as_markup()
