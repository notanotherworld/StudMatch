"""Inline и Reply клавиатуры для свайп-интерфейса."""
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List, Optional, Dict, Any, Set
from database.models import InterestTag, User, ModeEnum


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


def age_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура быстрого выбора возраста студента."""
    builder = InlineKeyboardBuilder()
    for a in [17, 18, 19, 20, 21, 22, 23, 24, 25]:
        builder.button(text=str(a), callback_data=f"age:{a}")
    builder.button(text="✍️ Другой возраст", callback_data="age:custom")
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
    builder.adjust(3, 3, 3, 1, 1)
    return builder.as_markup()


def year_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for y in range(1, 7):
        builder.button(text=f"{y} курс", callback_data=f"year:{y}")
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
    builder.adjust(3, 3, 1)
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
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
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
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


def target_gender_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора предпочтения по полу для знакомств."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👩 Девушек", callback_data="target_gender:female")
    builder.button(text="👨 Парней", callback_data="target_gender:male")
    builder.button(text="✨ Всех", callback_data="target_gender:all")
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
    builder.adjust(3, 1)
    return builder.as_markup()


def swipe_card_keyboard(profile_user_id: int, superlikes_count: int = 0) -> InlineKeyboardMarkup:
    """Кнопки действий под карточкой студента (свайп по одной анкеты)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Лайк", callback_data=f"swipe:like:{profile_user_id}")
    builder.button(text="⏭ Скип", callback_data=f"swipe:skip:{profile_user_id}")

    sl_label = f"⭐ Суперлайк ({superlikes_count})" if superlikes_count > 0 else "⭐ Суперлайк"
    builder.button(text=sl_label, callback_data=f"swipe:superlike:{profile_user_id}")
    builder.button(text="💌 Письмо", callback_data=f"swipe:message:{profile_user_id}")
    builder.button(text="🚨 Пожаловаться", callback_data=f"report:{profile_user_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def incoming_like_keyboard(from_user_id: int, portfolio_url: Optional[str] = None) -> InlineKeyboardMarkup:
    """Кнопки действий под карточкой входящего лайка или суперлайка."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Ответить взаимностью", callback_data=f"incoming:like:{from_user_id}")
    builder.button(text="⏭ Пропустить", callback_data=f"incoming:skip:{from_user_id}")
    if portfolio_url:
        builder.button(text="🔗 Портфолио", url=portfolio_url)
    builder.button(text="🚨 Пожаловаться", callback_data=f"report:{from_user_id}")
    if portfolio_url:
        builder.adjust(2, 1, 1)
    else:
        builder.adjust(2, 1)
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
    builder.button(text="❤️ Ответить взаимностью", callback_data=f"incoming:like:{from_user_id}")
    builder.button(text="⏭ Пропустить", callback_data=f"incoming:skip:{from_user_id}")
    builder.button(text="🚨 Пожаловаться", callback_data=f"report:{from_user_id}")
    builder.adjust(2, 1)
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
    builder.button(text="🚨 Пожаловаться", callback_data=f"report:{profile_user_id}")
    builder.adjust(1, 1)
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


def buy_superlike_keyboard(catalog: Optional[List[dict]] = None, pricing: Optional[dict] = None) -> InlineKeyboardMarkup:
    """Клавиатура покупки тарифов и услуг (динамически из каталога админки)."""
    builder = InlineKeyboardBuilder()

    if catalog:
        for item in catalog:
            if not item.get("is_active", True):
                continue
            emoji = item.get("emoji", "💎")
            name = item.get("name", "Услуга")
            price = item.get("price", 0)
            pid = item.get("id")
            builder.button(text=f"{emoji} {name} — {price} ₽", callback_data=f"buy:{pid}")
    else:
        pricing = pricing or {}
        p_vip = pricing.get("price_premium_1m", 199)
        p_boost = pricing.get("price_boost_24h", 99)
        p_sl3 = pricing.get("price_superlike_3", 49)
        p_sl10 = pricing.get("price_superlike_10", 199)
        builder.button(text=f"💎 Премиум-подписка — {p_vip} ₽/мес", callback_data="buy:premium_1m")
        builder.button(text=f"🛸 Буст — {p_boost} ₽/сутки", callback_data="buy:boost_24h")
        builder.button(text=f"⭐️ 3 суперлайка — {p_sl3} ₽", callback_data="buy:superlike_3")
        builder.button(text=f"⭐️ 10 суперлайков — {p_sl10} ₽", callback_data="buy:superlike_10")

    builder.button(text="🎁 Ввести промокод", callback_data="settings:enter_promo")
    builder.adjust(1)
    return builder.as_markup()


CAREER_SKILLS_LIST = [
    "🐍 Python / AI",
    "📊 Data Analytics / SQL",
    "💻 Frontend (React/Vue)",
    "⚙️ Backend (Go/Java/Node)",
    "🎨 UI/UX / Figma",
    "🚀 Product Management",
    "📈 Маркетинг / SMM",
    "📱 Mobile (iOS/Android)",
    "🧪 QA / Тестирование",
    "💼 Project Management",
    "💰 Sales / Продажи",
    "✍️ Копирайтинг / PR",
    "👥 HR / Рекрутинг",
    "🏛 FinTech / Финансы",
]


def career_skills_keyboard(selected: List[str] = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора профессиональных навыков/стека с чекбоксами."""
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for idx, skill in enumerate(CAREER_SKILLS_LIST):
        checked = "✅ " if skill in selected else ""
        builder.button(
            text=f"{checked}{skill}",
            callback_data=f"cskill:{idx}",
        )
    builder.button(text="✍️ Написать свой навык", callback_data="cskill:custom")
    builder.button(text="✔️ Готово", callback_data="cskill:done")
    builder.adjust(2)
    return builder.as_markup()


def career_work_format_keyboard() -> InlineKeyboardMarkup:
    """Выбор предпочтительного формата работы."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Удалённо (Remote)", callback_data="wformat:remote")
    builder.button(text="🏢 Офис (Office)", callback_data="wformat:office")
    builder.button(text="⚖️ Гибрид (Hybrid)", callback_data="wformat:hybrid")
    builder.button(text="⏱ Гибкий график / Part-time", callback_data="wformat:part_time")
    builder.button(text="❌ Пропустить", callback_data="wformat:skip")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def career_swipe_card_keyboard(
    profile_user_id: int, portfolio_url: Optional[str] = None, superlikes_count: int = 0
) -> InlineKeyboardMarkup:
    """Кнопки действий под карьерной анкетой студента."""
    builder = InlineKeyboardBuilder()
    if portfolio_url and portfolio_url.startswith("http"):
        builder.button(text="🔗 Портфолио / Резюме", url=portfolio_url)

    builder.button(text="🤝 Коннект", callback_data=f"swipe:like:{profile_user_id}")
    builder.button(text="⏭ Скип", callback_data=f"swipe:skip:{profile_user_id}")

    sl_label = f"⭐ Суперлайк ({superlikes_count})" if superlikes_count > 0 else "⭐ Суперлайк"
    builder.button(text=sl_label, callback_data=f"swipe:superlike:{profile_user_id}")
    builder.button(text="💌 Письмо", callback_data=f"swipe:message:{profile_user_id}")
    builder.button(text="🚨 Пожаловаться", callback_data=f"report:{profile_user_id}")

    if portfolio_url and portfolio_url.startswith("http"):
        builder.adjust(1, 2, 2, 1)
    else:
        builder.adjust(2, 2, 1)
    return builder.as_markup()


def my_profile_keyboard(user: User, current_view: str = "current") -> InlineKeyboardMarkup:
    """
    Клавиатура управления профилем:
    - Знакомства / Карьера (переключение вкладок)
    - Подтвердить статус студента (если не верифицирован)
    - Режим: [Знакомства / Карьера]
    - Мои достижения
    - Премиум и суперлайки
    - Пригласить друзей
    """
    p = user.profile
    dating_ok = "✅" if (p and p.is_complete) else "⚠️"
    career_ok = "✅" if (p and p.career_is_complete) else "⚠️"

    mode_label = "🎯 Карьера" if user.mode == ModeEnum.career else "❤️ Знакомства"
    builder = InlineKeyboardBuilder()

    # 1. Знакомства / Карьера (в 2 колонки)
    builder.button(text=f"❤️ Знакомства {dating_ok}", callback_data="profile:view_dating")
    builder.button(text=f"🎯 Карьера {career_ok}", callback_data="profile:view_career")

    # 2. Кто меня лайкнул
    builder.button(text="💌 Кто меня лайкнул", callback_data="profile:incoming_likes")

    # 3. Подтвердить статус студента (если еще не подтвержден)
    if not user.email_verified:
        builder.button(text="🎓 Подтвердить статус (+100⭐)", callback_data="auth:start_verification")

    # 4. Режим
    builder.button(text=f"Режим: {mode_label} 🔄", callback_data="settings:change_mode")
    # 5. Мои достижения
    builder.button(text="🏆 Мои достижения", callback_data="settings:achievements")
    # 6. Премиум и суперлайки
    is_prem = getattr(user, "is_premium", False)
    prem_label = "💎 Премиум активен (Продлить)" if is_prem else "💎 Получить Премиум"
    builder.button(text=prem_label, callback_data="settings:buy")
    # 7. Пригласить друзей
    builder.button(text="🪢 Пригласить друзей (+3 ⭐️)", callback_data="settings:ref_link")

    if not user.email_verified:
        builder.adjust(2, 1, 1, 1, 1, 1, 1)
    else:
        builder.adjust(2, 1, 1, 1, 1, 1)
    return builder.as_markup()


def settings_keyboard(current_mode: str, is_visible: bool = True, email_verified: bool = True) -> InlineKeyboardMarkup:
    """
    Клавиатура Настроек:
    - Подтвердить статус студента (если не верифицирован)
    - Скрыть из поиска / Показать в поиске
    - Фильтры поиска (Возраст, Курс, Факультет)
    - Сбросить историю свайпов
    - Изменить интересы
    - Изменить фото и видео
    - Пол и предпочтения
    - Промокод
    - Редактировать анкету
    """
    builder = InlineKeyboardBuilder()

    if not email_verified:
        builder.button(text="🎓 Подтвердить статус студента (+100⭐)", callback_data="auth:start_verification")

    vis_label = "🔒 Скрыть из поиска" if is_visible else "👁 Показать в поиске"
    builder.button(text=vis_label, callback_data="settings:toggle_visibility")
    builder.button(text="🎯 Фильтры поиска", callback_data="settings:filters")
    builder.button(text="🏷 Изменить интересы", callback_data="settings:edit_interests")
    builder.button(text="📸 Изменить фото и видео", callback_data="settings:edit_media")
    builder.button(text="👫 Пол и предпочтения", callback_data="settings:edit_gender")
    builder.button(text="🎁 Промокод", callback_data="settings:enter_promo")
    builder.button(text="✏️ Редактировать анкету", callback_data="settings:choose_edit_profile")

    builder.adjust(1)
    return builder.as_markup()


def search_filters_keyboard(profile: Any = None) -> InlineKeyboardMarkup:
    """Клавиатура настройки фильтров выдачи анкет."""
    min_a = getattr(profile, "filter_min_age", None) or 17
    max_a = getattr(profile, "filter_max_age", None) or 30
    min_y = getattr(profile, "filter_min_year", None) or 1
    max_y = getattr(profile, "filter_max_year", None) or 6
    major = getattr(profile, "filter_major", None)
    major_label = major if major and major != "all" else "✨ Любой"

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🎂 Возраст: {min_a}–{max_a} лет ✏️", callback_data="filter:edit_age")
    builder.button(text=f"🎓 Курс: {min_y}–{max_y} курс ✏️", callback_data="filter:edit_year")
    builder.button(text=f"🏛 Факультет: {major_label} ✏️", callback_data="filter:edit_major")
    builder.button(text="🔄 Сбросить все фильтры", callback_data="filter:reset")
    builder.button(text="🔙 Назад в настройки", callback_data="settings:back_to_settings")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def filter_age_keyboard() -> InlineKeyboardMarkup:
    """Выбор диапазона возраста для фильтра поиска."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👶 17–20 лет (Младшие курсы)", callback_data="filter_set_age:17:20")
    builder.button(text="🧑‍🎓 18–24 лет (Бакалавриат)", callback_data="filter_set_age:18:24")
    builder.button(text="🎓 20–28 лет (Старшие и Магистры)", callback_data="filter_set_age:20:28")
    builder.button(text="✨ Любой возраст (16–35)", callback_data="filter_set_age:16:35")
    builder.button(text="✍️ Ввести свой диапазон", callback_data="filter_set_age:custom")
    builder.button(text="🔙 Назад к фильтрам", callback_data="settings:filters")
    builder.adjust(1)
    return builder.as_markup()


def filter_year_keyboard() -> InlineKeyboardMarkup:
    """Выбор курса для фильтра поиска."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🌱 1–2 курс (Младшие)", callback_data="filter_set_year:1:2")
    builder.button(text="🌿 3–4 курс (Старшие)", callback_data="filter_set_year:3:4")
    builder.button(text="🌳 5–6 курс / Магистратура", callback_data="filter_set_year:5:6")
    builder.button(text="✨ Любой курс (1–6)", callback_data="filter_set_year:1:6")
    builder.button(text="🔙 Назад к фильтрам", callback_data="settings:filters")
    builder.adjust(1)
    return builder.as_markup()


def filter_major_keyboard() -> InlineKeyboardMarkup:
    """Выбор института/факультета для фильтра поиска."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✨ Любой факультет / институт", callback_data="filter_set_major:all")
    for idx, inst in enumerate(RUDN_INSTITUTES):
        builder.button(text=f"🏛 {inst}", callback_data=f"filter_set_major:{idx}")
    builder.button(text="🔙 Назад к фильтрам", callback_data="settings:filters")
    builder.adjust(1)
    return builder.as_markup()


def edit_profile_choice_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора анкеты для редактирования (Знакомства / Карьера)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ Знакомства", callback_data="settings:edit_profile")
    builder.button(text="🎯 Карьера", callback_data="settings:edit_career_profile")
    builder.button(text="🔙 Назад в настройки", callback_data="settings:back_to_settings")
    builder.adjust(2, 1)
    return builder.as_markup()


def media_upload_keyboard(uploaded_photos_count: int = 0, has_video: bool = False, can_keep_existing: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура управления загрузкой медиа (до 3 фото и 1 видео)."""
    builder = InlineKeyboardBuilder()
    if uploaded_photos_count > 0:
        builder.button(text="✔️ Завершить загрузку", callback_data="media:done")
    elif can_keep_existing:
        builder.button(text="📸 Оставить текущие фото/видео", callback_data="media:keep_existing")
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
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


def cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой '❌ Отмена' во время заполнения/редактирования анкеты."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True, input_field_placeholder="Введи ответ или нажми Отмена...")


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
