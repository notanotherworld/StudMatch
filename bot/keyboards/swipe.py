"""Inline и Reply клавиатуры для свайп-интерфейса."""
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List
from database.models import InterestTag


def consent_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принимаю", callback_data="consent:accept")
    builder.button(text="❌ Отказаться", callback_data="consent:decline")
    builder.adjust(1)
    return builder.as_markup()


def mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Карьера", callback_data="mode:career")
    builder.button(text="❤️ Знакомства", callback_data="mode:dating")
    builder.adjust(2)
    return builder.as_markup()


def year_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for y in range(1, 7):
        builder.button(text=f"{y} курс", callback_data=f"year:{y}")
    builder.adjust(3)
    return builder.as_markup()


def interests_keyboard(tags: List[InterestTag], selected: List[int] = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора интересов с чекбоксами."""
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for tag in tags:
        checked = "✅ " if tag.id in selected else ""
        builder.button(
            text=f"{checked}{tag.emoji} {tag.name}",
            callback_data=f"interest:{tag.id}",
        )
    builder.button(text="✔️ Готово", callback_data="interest:done")
    builder.adjust(2)
    return builder.as_markup()


def swipe_card_keyboard(profile_user_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий под карточкой студента."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Лайк", callback_data=f"swipe:like:{profile_user_id}")
    builder.button(text="⭐ Суперлайк", callback_data=f"swipe:superlike:{profile_user_id}")
    builder.button(text="⏭ Скип", callback_data=f"swipe:skip:{profile_user_id}")
    builder.adjust(3)
    return builder.as_markup()


def top_navigation_keyboard(page: int, total_pages: int = 2) -> InlineKeyboardMarkup:
    """Навигация по страницам топа (1/2 → 2/2)."""
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="◀️", callback_data=f"top:page:{page - 1}")
    builder.button(text=f"{page}/{total_pages}", callback_data="top:noop")
    if page < total_pages:
        builder.button(text="▶️", callback_data=f"top:page:{page + 1}")
    builder.adjust(3)
    return builder.as_markup()


def profile_open_keyboard(profile_user_id: int) -> InlineKeyboardMarkup:
    """Кнопка открыть полный профиль из топа."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👁 Открыть профиль", callback_data=f"profile:open:{profile_user_id}")
    builder.adjust(1)
    return builder.as_markup()


def achievement_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    types = [
        ("📊 GPA / Успеваемость", "gpa"),
        ("🏆 Победа в олимпиаде", "olympiad"),
        ("💼 Кейс-чемпионат", "case"),
        ("🥇 Соревнования", "competition"),
        ("🎓 Диплом с отличием", "diploma"),
        ("📝 Публикация", "publication"),
        ("🎯 Участие", "participation"),
    ]
    for label, ach_type in types:
        builder.button(text=label, callback_data=f"ach_type:{ach_type}")
    builder.adjust(1)
    return builder.as_markup()


def buy_superlike_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="3 суперлайка — 99 ₽", callback_data="buy:superlike_3")
    builder.button(text="10 суперлайков — 249 ₽", callback_data="buy:superlike_10")
    builder.button(text="⚡ Буст анкеты 24ч — 149 ₽", callback_data="buy:boost_24h")
    builder.adjust(1)
    return builder.as_markup()


def settings_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    mode_label = "🎯 Карьера" if current_mode == "career" else "❤️ Знакомства"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Режим: {mode_label}", callback_data="settings:change_mode")
    builder.button(text="✏️ Редактировать анкету", callback_data="settings:edit_profile")
    builder.button(text="🏆 Мои достижения", callback_data="settings:achievements")
    builder.button(text="⭐ Купить суперлайки", callback_data="settings:buy")
    builder.button(text="👁 Скрыть / показать анкету", callback_data="settings:toggle_visibility")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🏆 Топ студентов")
    builder.button(text="💘 Мои мэтчи")
    builder.button(text="👤 Мой профиль")
    builder.button(text="⚙️ Настройки")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
