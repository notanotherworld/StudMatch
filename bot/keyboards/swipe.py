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


RUDN_INSTITUTES = [
    "Аграрно-технологический институт",
    "Институт фармации и биотехнологии",
    "Институт внешнеэкономической безопасности и таможенного дела",
    "Институт русского языка",
    "Институт иностранных языков",
    "Институт мировой экономики и бизнеса",
    "Институт экологии",
    "Медицинский институт",
    "НОИ современных языков и коммуникаций",
    "УНИ гравитации и космологии",
    "УНИ сравнительной образовательной политики",
    "Юридический институт",
    "УНИ клинической медицины",
    "Инженерная академия",
    "Высшая школа управления",
]


def rudn_institutes_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, inst in enumerate(RUDN_INSTITUTES):
        builder.button(text=inst, callback_data=f"major_idx:{idx}")
    builder.adjust(1)
    return builder.as_markup()


def interests_keyboard(tags: List[InterestTag], selected: List[int] = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора интересов с чекбоксами и кастомным вводом (без эмодзи)."""
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for tag in tags:
        checked = "✅ " if tag.id in selected else ""
        builder.button(
            text=f"{checked}{tag.name}",
            callback_data=f"interest:{tag.id}",
        )
    builder.button(text="✍️ Написать свой", callback_data="interest:custom")
    builder.button(text="✔️ Готово", callback_data="interest:done")
    builder.adjust(2)
    return builder.as_markup()


def gender_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора пола пользователя."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👨 Парень", callback_data="gender:male")
    builder.button(text="👩 Девушка", callback_data="gender:female")
    builder.adjust(2)
    return builder.as_markup()


def target_gender_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора предпочтения по полу для знакомств."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👩 Девушек", callback_data="target_gender:female")
    builder.button(text="👨 Парней", callback_data="target_gender:male")
    builder.button(text="✨ Всех", callback_data="target_gender:all")
    builder.adjust(3)
    return builder.as_markup()


def swipe_card_keyboard(profile_user_id: int, superlikes_count: int = 0) -> InlineKeyboardMarkup:
    """Кнопки действий под карточкой студента (свайп по одной анкеты)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Лайк", callback_data=f"swipe:like:{profile_user_id}")
    builder.button(text="⏭ Скип", callback_data=f"swipe:skip:{profile_user_id}")

    sl_label = f"⭐ Суперлайк ({superlikes_count})" if superlikes_count > 0 else "⭐ Суперлайк"
    builder.button(text=sl_label, callback_data=f"swipe:superlike:{profile_user_id}")
    builder.button(text="💌 Письмо", callback_data=f"swipe:message:{profile_user_id}")
    builder.adjust(2, 2)
    return builder.as_markup()


def match_keyboard(tg_username: str = "") -> InlineKeyboardMarkup:
    """Кнопка прямого перехода в диалог при мэтче."""
    builder = InlineKeyboardBuilder()
    if tg_username and tg_username != "(нет username)":
        clean_user = tg_username.lstrip("@")
        builder.button(text="💬 Написать в Telegram", url=f"https://t.me/{clean_user}")
    builder.button(text="🔥 Искать дальше", callback_data="top:swipe_next")
    builder.adjust(1)
    return builder.as_markup()


def letter_received_keyboard(from_user_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий для получателя письма."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Лайкнуть в ответ", callback_data=f"swipe:like:{from_user_id}")
    builder.button(text="👀 Профиль", callback_data=f"profile:open:{from_user_id}")
    builder.button(text="⏭ Пропустить", callback_data=f"swipe:skip:{from_user_id}")
    builder.adjust(1, 2)
    return builder.as_markup()


def top_navigation_keyboard(page: int, total_pages: int = 2) -> InlineKeyboardMarkup:
    """Навигация по страницам топа + кнопка Как попасть в топ."""
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="◀️ Назад", callback_data=f"top:page:{page - 1}")
    builder.button(text=f"Стр. {page}/{total_pages}", callback_data="top:noop")
    if page < total_pages:
        builder.button(text="Вперёд ▶️", callback_data=f"top:page:{page + 1}")
    builder.button(text="❓ Как попасть в топ", callback_data="top:how_to")
    builder.adjust(3, 1)
    return builder.as_markup()


def profile_open_keyboard(profile_user_id: int) -> InlineKeyboardMarkup:
    """Кнопка открыть полный профиль из топа."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👀 Открыть профиль", callback_data=f"profile:open:{profile_user_id}")
    builder.adjust(1)
    return builder.as_markup()


def achievement_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    types = [
        ("💼 Участие в хакатоне / кейс-чемпионате (+25 б.)", "case_participant"),
        ("🥉 Призовое 3-е место (+50 б.)", "place_3"),
        ("🥈 Призовое 2-е место (+75 б.)", "place_2"),
        ("🥇 Победа / 1-е место (+100 б.)", "place_1"),
        ("🤝 Участие в волонтёрском проекте (+20 б.)", "volunteer"),
        ("👔 Прохождение стажировки (+60 б.)", "internship"),
        ("🏛 Посещение форума / конференции (+15 б.)", "forum_attender"),
        ("🎤 Выступление на форуме / конференции (+40 б.)", "forum_speaker"),
    ]
    for label, ach_type in types:
        builder.button(text=label, callback_data=f"ach_type:{ach_type}")
    builder.adjust(1)
    return builder.as_markup()


def buy_superlike_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Премиум-подписка — 199 ₽/мес", callback_data="buy:premium_1m")
    builder.button(text="⭐️ 3 суперлайка — 49 ₽", callback_data="buy:superlike_3")
    builder.button(text="⭐️ 5 суперлайков — 99 ₽", callback_data="buy:superlike_5")
    builder.button(text="🛸 Буст — 99 ₽/сутки", callback_data="buy:boost_24h")
    builder.adjust(1)
    return builder.as_markup()


def my_profile_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    mode_label = "🎯 Карьера" if current_mode == "career" else "❤️ Знакомства"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Режим: {mode_label}", callback_data="settings:change_mode")
    builder.button(text="✏️ Изменить анкету", callback_data="settings:edit_profile")
    builder.button(text="🏆 Мои достижения", callback_data="settings:achievements")
    builder.button(text="💎 Премиум и Суперлайки", callback_data="settings:buy")
    builder.button(text="🪢 Пригласить друга (+3 ⭐️)", callback_data="settings:ref_link")
    builder.adjust(1)
    return builder.as_markup()


def settings_keyboard(current_mode: str, is_visible: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏷 Изменить интересы", callback_data="settings:edit_interests")
    builder.button(text="👫 Пол и предпочтения", callback_data="settings:edit_gender")
    vis_label = "🔒 Скрыть из поиска" if is_visible else "👁 Показывать в поиске"
    builder.button(text=vis_label, callback_data="settings:toggle_visibility")
    builder.button(text="🔄 Сбросить историю свайпов", callback_data="settings:reset_swipes")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔍 Смотреть анкеты")
    builder.button(text="🏅 Зал славы")
    builder.button(text="🫂 Мои мэтчи")
    builder.button(text="🐾 Мой профиль")
    builder.button(text="⚙️ Настройки")
    builder.button(text="🪢 Пригласить друга (+3 ⭐️)")
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True, input_field_placeholder="Выбери раздел...")


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
