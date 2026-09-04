"""
Настройки: смена режима, видимость анкеты, покупка суперлайков.
"""
import html
from typing import Optional, List, Dict, Any, Set
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.swipe import (
    settings_keyboard, my_profile_keyboard, mode_keyboard,
    buy_superlike_keyboard, main_menu_keyboard, interests_keyboard, gender_keyboard,
    edit_profile_choice_keyboard,
    search_filters_keyboard, filter_age_keyboard, filter_year_keyboard, filter_major_keyboard,
    RUDN_INSTITUTES,
)
from bot.states.fsm import ProfileState, FilterState
from database.crud import set_user_mode
from database.models import User, ModeEnum, Profile, InterestTag, Swipe
from bot.utils.dynamic_settings import get_dynamic_pricing

def format_age(age: Optional[int]) -> str:
    if not age:
        return ""
    if 11 <= (age % 100) <= 19:
        suffix = "лет"
    elif age % 10 == 1:
        suffix = "год"
    elif age % 10 in (2, 3, 4):
        suffix = "года"
    else:
        suffix = "лет"
    return f", {age} {suffix}"

router = Router()


@router.message(StateFilter("*"), F.text.in_({"⚙️ Настройки", "Настройки", "/settings"}))
async def show_settings(message: Message, user: User, state: FSMContext = None):
    if state:
        await state.clear()
    is_vis = user.profile.is_visible if user.profile else True
    await message.answer(
        "⚙️ <b>Настройки</b>",
        parse_mode="HTML",
        reply_markup=settings_keyboard(user.mode.value, is_visible=is_vis, email_verified=user.email_verified),
    )


@router.callback_query(F.data == "auth:start_verification")
async def start_verification_callback(callback: CallbackQuery, state: FSMContext, user: User):
    """Запуск процесса верификации студента из настроек или профиля."""
    await callback.answer()
    if user.email_verified:
        await callback.message.answer("✅ <b>Твой студенческий статус уже верифицирован!</b>", parse_mode="HTML")
        return

    from bot.states.fsm import AuthState
    await state.set_state(AuthState.waiting_email)
    await callback.message.answer(
        "🎓 <b>Верификация студента</b>\n\n"
        "Введи свой корпоративный email университета.\n"
        "Например: <code>ivanov@rudn.ru</code>\n\n"
        "✨ <b>После подтверждения ты получишь:</b>\n"
        "• Бейдж <b>[ 🎓 Верифицирован ]</b> в анкете\n"
        "• <b>+100 баллов</b> к рейтингу в Зале славы ⭐\n"
        "• <b>+3 ⭐️ Суперлайка</b> на баланс\n"
        "• Приоритет при показе анкеты в ленте свайпов 🚀",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:change_mode")
async def change_mode_prompt(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Выбери режим:",
        reply_markup=mode_keyboard(),
    )


@router.callback_query(F.data == "settings:edit_interests")
async def edit_interests_prompt(callback: CallbackQuery, user: User, state: FSMContext, db: AsyncSession):
    await callback.answer()
    if not user.profile:
        await callback.answer("Сначала заполни анкету!", show_alert=True)
        return

    selected = list(user.profile.interest_ids or [])
    custom_interests = user.profile.custom_interests
    await state.update_data(
        selected_interests=selected,
        custom_interests=custom_interests,
        editing_from_settings=True,
    )
    await state.set_state(ProfileState.waiting_interests)

    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())
    custom_note = f"\n\n✍️ <i>Текущий свой интерес: {user.profile.custom_interests}</i>" if user.profile.custom_interests else ""
    await callback.message.answer(
        f"Выбери интересующие теги или нажми <b>✍️ Написать свой</b>:{custom_note}",
        parse_mode="HTML",
        reply_markup=interests_keyboard(tags, selected),
    )


@router.callback_query(F.data == "settings:choose_edit_profile")
async def choose_edit_profile_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "✏️ <b>Какую анкету вы хотите отредактировать?</b>\n\n"
        "• <b>Знакомства</b> — анкета для общения, хобби, поиска друзей и отношений\n"
        "• <b>Карьера</b> — профессиональная анкета с навыками, стеком технологий и резюме"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=edit_profile_choice_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=edit_profile_choice_keyboard())


@router.callback_query(F.data == "settings:back_to_settings")
async def back_to_settings_callback(callback: CallbackQuery, user: User):
    await callback.answer()
    is_vis = user.profile.is_visible if user.profile else True
    text = "⚙️ <b>Настройки</b>"
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=settings_keyboard(user.mode.value, is_visible=is_vis, email_verified=user.email_verified),
        )
    except Exception:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=settings_keyboard(user.mode.value, is_visible=is_vis, email_verified=user.email_verified),
        )


@router.callback_query(F.data == "settings:edit_profile")
async def edit_profile_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.profile import start_profile_creation
    await start_profile_creation(callback.message, state)


@router.callback_query(F.data == "settings:edit_gender")
async def edit_gender_prompt(callback: CallbackQuery, state: FSMContext):
    await state.update_data(editing_gender_from_settings=True)
    await state.set_state(ProfileState.waiting_gender)
    await callback.answer()
    await callback.message.answer(
        "👫 <b>Выбери твой пол:</b>",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
    )


@router.callback_query(F.data == "settings:edit_media")
async def edit_media_prompt(callback: CallbackQuery, state: FSMContext, user: User):
    await callback.answer()
    from bot.keyboards.swipe import media_upload_keyboard
    await state.set_state(ProfileState.waiting_photo)
    await state.update_data(photos=[], video_file_id=None, editing_media_from_settings=True)
    await callback.message.answer(
        "📸 <b>Обновление фото и видео в анкете:</b>\n\n"
        "• Можно отправить <b>сразу альбомом</b> или по одному: <b>до 3 фото</b> и <b>1 видео</b> (до 10 МБ 🎥).\n"
        "• Первое отправленное фото станет твоей главной аватаркой.\n\n"
        "<i>Выбери в галерее и отправь сразу 3 фото + видео, затем нажми <b>✔️ Завершить загрузку</b></i>",
        parse_mode="HTML",
        reply_markup=media_upload_keyboard(0, False),
    )


@router.callback_query(F.data == "settings:edit_career_profile")
async def edit_career_profile_prompt(callback: CallbackQuery, user: User, state: FSMContext, db: AsyncSession):
    await callback.answer()
    from bot.handlers.profile import start_career_profile_creation
    await start_career_profile_creation(callback, state, user, db)


@router.callback_query(F.data == "profile:view_dating")
async def view_dating_profile_callback(callback: CallbackQuery, user: User, db: AsyncSession):
    await callback.answer()
    await show_my_profile(callback.message, user, db, view_mode="dating")


@router.callback_query(F.data == "profile:view_career")
async def view_career_profile_callback(callback: CallbackQuery, user: User, db: AsyncSession):
    await callback.answer()
    await show_my_profile(callback.message, user, db, view_mode="career")


@router.callback_query(F.data.startswith("mode:"))
async def set_mode(callback: CallbackQuery, user: User, db: AsyncSession, state: FSMContext = None):
    mode_str = callback.data.split(":")[1]
    mode = ModeEnum.career if mode_str == "career" else ModeEnum.dating
    await set_user_mode(db, user.id, mode)

    label = "🎯 Карьера" if mode == ModeEnum.career else "❤️ Знакомства"
    await callback.answer(f"Режим изменён: {label}")
    await callback.message.edit_reply_markup(reply_markup=None)

    if mode == ModeEnum.career and (not user.profile or not user.profile.career_is_complete):
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="🚀 Заполнить анкету Карьеры", callback_data="settings:edit_career_profile")
        builder.adjust(1)
        await callback.message.answer(
            f"✅ Режим изменён на <b>{label}</b>\n\n"
            "⚠️ <b>Твоя профессиональная анкета ещё не заполнена!</b>\n"
            "Укажи свои навыки, стек технологий и формат работы, чтобы тебя видели работодатели (HR) и студенты.",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        return

    extra_text = (
        "\n\n💼 <i>Компании видят топ-50. Чем выше ты в этом списке, тем чаще они пишут тебе первыми. Все получится 🤲🏻</i>"
        if mode == ModeEnum.career else ""
    )
    await callback.message.answer(
        f"✅ Режим изменён на <b>{label}</b>{extra_text}",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "settings:toggle_visibility")
async def toggle_visibility(callback: CallbackQuery, user: User, db: AsyncSession):
    if not user.profile:
        await callback.answer("Сначала заполни анкету!")
        return

    new_state = not user.profile.is_visible
    await db.execute(
        update(Profile).where(Profile.user_id == user.id).values(is_visible=new_state)
    )
    await db.commit()

    label = "включена в поиске" if new_state else "скрыта из поиска"
    await callback.answer(f"Твоя анкета {label}!")
    try:
        await callback.message.edit_reply_markup(
            reply_markup=settings_keyboard(user.mode.value, is_visible=new_state, email_verified=user.email_verified)
        )
    except Exception:
        pass

    msg = (
        "👀 <b>Твоя анкета снова отображается в поиске!</b>\nДругие студенты смогут находить тебя при свайпах."
        if new_state
        else "🔒 <b>Твоя анкета скрыта из поиска!</b>\nОна не будет появляться при свайпах, но останется в Зале славы."
    )
    await callback.message.answer(msg, parse_mode="HTML")


@router.callback_query(F.data == "settings:reset_swipes")
@router.message(F.text == "/reset_swipes")
async def reset_user_swipes(event, user: User, db: AsyncSession):
    from bot.config import settings
    admin_ids = [int(x.strip()) for x in str(settings.ADMIN_IDS).split(",") if x.strip().isdigit()]
    is_admin = user.id in admin_ids or getattr(user, "is_fake", False)

    if not is_admin:
        if isinstance(event, CallbackQuery):
            await event.answer("Команда доступна только администраторам и тестировщикам.", show_alert=True)
        else:
            await event.answer("⚠️ Команда доступна только администраторам и тестировщикам.")
        return

    from sqlalchemy import delete
    from database.models import Swipe
    await db.execute(delete(Swipe).where(Swipe.from_user_id == user.id))
    await db.commit()

    msg_text = (
        "🔄 <b>История свайпов полностью сброшена!</b>\n\n"
        "Теперь нажми <b>🔍 Смотреть анкеты</b> в меню, чтобы просмотреть анкеты заново."
    )

    if isinstance(event, CallbackQuery):
        await event.answer("Свайпы сброшены!")
        await event.message.answer(msg_text, parse_mode="HTML")
    else:
        await event.answer(msg_text, parse_mode="HTML")



# ─── Фильтры поиска анкет ─────────────────────────────────────
@router.callback_query(F.data == "settings:filters")
async def show_search_filters(callback: CallbackQuery, user: User):
    await callback.answer()
    prof = user.profile
    min_a = prof.filter_min_age if prof and prof.filter_min_age else 17
    max_a = prof.filter_max_age if prof and prof.filter_max_age else 30
    min_y = prof.filter_min_year if prof and prof.filter_min_year else 1
    max_y = prof.filter_max_year if prof and prof.filter_max_year else 6
    major = prof.filter_major if prof and prof.filter_major and prof.filter_major != "all" else "✨ Любой"

    text = (
        "🎯 <b>Настройки фильтров поиска анкет</b>\n\n"
        "Укажи параметры студентов, которых ты хочешь встречать при свайпах:\n\n"
        f"🎂 <b>Возраст:</b> {min_a}–{max_a} лет\n"
        f"🎓 <b>Курс:</b> {min_y}–{max_y} курс\n"
        f"🏛 <b>Факультет / Институт:</b> {major}\n\n"
        "<i>Нажми на кнопку ниже, чтобы изменить фильтр:</i>"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=search_filters_keyboard(prof))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=search_filters_keyboard(prof))


@router.callback_query(F.data == "filter:edit_age")
async def filter_edit_age_prompt(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🎂 <b>Фильтр по возрасту</b>\n\n"
        "Выбери желаемый возрастной диапазон студентов или введи свой:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=filter_age_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=filter_age_keyboard())


@router.callback_query(F.data.startswith("filter_set_age:"))
async def filter_set_age_callback(callback: CallbackQuery, user: User, state: FSMContext, db: AsyncSession):
    val = callback.data.split("filter_set_age:")[1]
    if val == "custom":
        await callback.answer()
        await state.set_state(FilterState.waiting_custom_age_range)
        await callback.message.answer(
            "✍️ Напиши желаемый диапазон возраста через дефис (например: <code>18-23</code> или <code>19-27</code>):",
            parse_mode="HTML",
        )
        return

    parts = val.split(":")
    min_a, max_a = int(parts[0]), int(parts[1])
    await db.execute(
        update(Profile)
        .where(Profile.user_id == user.id)
        .values(filter_min_age=min_a, filter_max_age=max_a)
    )
    await db.commit()
    await callback.answer(f"Возраст: {min_a}–{max_a} лет", show_alert=True)
    prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
    user.profile = prof_res.scalar_one_or_none()
    await show_search_filters(callback, user)


@router.message(FilterState.waiting_custom_age_range)
async def process_custom_age_range(message: Message, state: FSMContext, user: User, db: AsyncSession):
    if not message.text:
        await message.answer("⚠️ Пожалуйста, укажи диапазон в формате <code>18-24</code>:", parse_mode="HTML")
        return
    text_val = message.text.strip().replace(" ", "")
    import re
    match = re.match(r"^(\d{2})[-–—](\d{2})$", text_val)
    if not match:
        await message.answer("⚠️ Пожалуйста, укажи диапазон в формате <code>18-24</code>:")
        return

    min_a, max_a = int(match.group(1)), int(match.group(2))
    if min_a > max_a:
        min_a, max_a = max_a, min_a

    if min_a < 16 or max_a > 60:
        await message.answer("⚠️ Возраст должен быть в пределах от 16 до 60 лет. Попробуй ещё раз:")
        return

    await state.clear()
    await db.execute(
        update(Profile)
        .where(Profile.user_id == user.id)
        .values(filter_min_age=min_a, filter_max_age=max_a)
    )
    await db.commit()

    prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
    user.profile = prof_res.scalar_one_or_none()

    await message.answer(f"✅ Фильтр возраста установлен: <b>{min_a}–{max_a} лет</b>!", parse_mode="HTML")
    min_y = user.profile.filter_min_year if user.profile.filter_min_year else 1
    max_y = user.profile.filter_max_year if user.profile.filter_max_year else 6
    major = user.profile.filter_major if user.profile.filter_major and user.profile.filter_major != "all" else "✨ Любой"
    text = (
        "🎯 <b>Настройки фильтров поиска анкет</b>\n\n"
        "Укажи параметры студентов, которых ты хочешь встречать при свайпах:\n\n"
        f"🎂 <b>Возраст:</b> {min_a}–{max_a} лет\n"
        f"🎓 <b>Курс:</b> {min_y}–{max_y} курс\n"
        f"🏛 <b>Факультет / Институт:</b> {major}\n\n"
        "<i>Нажми на кнопку ниже, чтобы изменить фильтр:</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=search_filters_keyboard(user.profile))


@router.callback_query(F.data == "filter:edit_year")
async def filter_edit_year_prompt(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🎓 <b>Фильтр по курсу</b>\n\n"
        "Выбери, студентов каких курсов показывать в ленте:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=filter_year_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=filter_year_keyboard())


@router.callback_query(F.data.startswith("filter_set_year:"))
async def filter_set_year_callback(callback: CallbackQuery, user: User, db: AsyncSession):
    val = callback.data.split("filter_set_year:")[1]
    parts = val.split(":")
    min_y, max_y = int(parts[0]), int(parts[1])
    await db.execute(
        update(Profile)
        .where(Profile.user_id == user.id)
        .values(filter_min_year=min_y, filter_max_year=max_y)
    )
    await db.commit()
    await callback.answer(f"Курс: {min_y}–{max_y}", show_alert=True)
    prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
    user.profile = prof_res.scalar_one_or_none()
    await show_search_filters(callback, user)


@router.callback_query(F.data == "filter:edit_major")
async def filter_edit_major_prompt(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🏛 <b>Фильтр по факультету / институту</b>\n\n"
        "Выбери институт РУДН для поиска студентов или «Любой»:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=filter_major_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=filter_major_keyboard())


@router.callback_query(F.data.startswith("filter_set_major:"))
async def filter_set_major_callback(callback: CallbackQuery, user: User, db: AsyncSession):
    val = callback.data.split("filter_set_major:")[1]
    if val == "all":
        major_val = None
        alert_text = "Факультет: Любой"
    else:
        idx = int(val)
        major_val = RUDN_INSTITUTES[idx] if 0 <= idx < len(RUDN_INSTITUTES) else None
        alert_text = f"Факультет: {major_val}"

    await db.execute(
        update(Profile)
        .where(Profile.user_id == user.id)
        .values(filter_major=major_val)
    )
    await db.commit()
    await callback.answer(alert_text, show_alert=True)
    prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
    user.profile = prof_res.scalar_one_or_none()
    await show_search_filters(callback, user)


@router.callback_query(F.data == "filter:reset")
async def filter_reset_callback(callback: CallbackQuery, user: User, db: AsyncSession):
    await db.execute(
        update(Profile)
        .where(Profile.user_id == user.id)
        .values(filter_min_age=17, filter_max_age=30, filter_min_year=1, filter_max_year=6, filter_major=None)
    )
    await db.commit()
    await callback.answer("Все фильтры поиска сброшены к стандартным!", show_alert=True)
    prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
    user.profile = prof_res.scalar_one_or_none()
    await show_search_filters(callback, user)


@router.callback_query(F.data == "settings:buy")
async def show_buy(callback: CallbackQuery, user: User):
    await callback.answer()
    balance = user.superlike_balance
    from bot.utils.dynamic_settings import get_payment_products_catalog
    catalog = await get_payment_products_catalog()
    active_products = [p for p in catalog if p.get("is_active", True)]

    lines = ["💎 <b>Тарифы, суперлайки и услуги СтудМэч</b>\n"]
    for p in active_products:
        emoji = p.get("emoji", "💎")
        name = p.get("name", "Услуга")
        price = p.get("price", 0)
        desc = p.get("description", "")
        desc_str = f"\n<i>{desc}</i>" if desc else ""
        lines.append(f"{emoji} <b>{name}</b> — <b>{price} ₽</b>{desc_str}")

    lines.append(f"\nБаланс суперлайков: <b>{balance}</b> ⭐️")
    lines.append("👉 <i>Выбери тариф для оплаты ниже:</i>")

    text = "\n\n".join(lines)

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=buy_superlike_keyboard(catalog=active_products),
    )


@router.message(StateFilter("*"), F.text.func(lambda t: bool(t and ("Пригласить" in t or "ref" in t.lower()))))
@router.callback_query(F.data == "settings:ref_link")
async def show_referral_link(event, user: User, state: FSMContext = None):
    if state:
        await state.clear()
    bot_info = await event.bot.get_me()
    ref_url = f"https://t.me/{bot_info.username}?start=ref_{user.id}"

    from urllib.parse import quote
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    share_text = "Привет! Студмэч🌤 - твоя экосистема в вузе: проекты, работа, друзья и любовь в одном боте. Присоединяйся))"
    share_url = f"https://t.me/share/url?url={quote(ref_url)}&text={quote(share_text)}"

    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Поделиться с другом", url=share_url)

    text = (
        f"🔗 <b>Приглашай друзей в СтудМэч!</b>\n\n"
        f"Нажми на ссылку ниже или кнопку <b>«🚀 Поделиться с другом»</b>:\n"
        f"👉 <a href=\"{ref_url}\">{ref_url}</a>\n\n"
        f"🎁 За каждого зарегистрировавшегося друга ты получаешь <b>+3 ⭐️ Суперлайка</b>!"
    )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup(), disable_web_page_preview=True)
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup(), disable_web_page_preview=True)


@router.message(StateFilter("*"), F.text.in_({"🐾 Мой профиль", "👤 Мой профиль", "Мой профиль", "/profile"}))
async def show_my_profile(
    message: Message,
    user: User,
    db: AsyncSession,
    state: FSMContext = None,
    view_mode: str = "current",
):
    if state:
        await state.clear()
    profile = user.profile
    if not profile or not profile.name:
        await message.answer("У тебя ещё нет анкеты. Напиши /start чтобы создать.")
        return

    score_val = profile.rating_score or 0.0
    year_str = f"{profile.year} курс" if profile.year else "Студент"
    name = html.escape(profile.name or "Студент")
    major = html.escape(profile.major or "")
    email_str = html.escape(user.email or "не указан")

    # Определяем какой режим показывать
    is_career_view = (view_mode == "career") or (view_mode == "current" and user.mode == ModeEnum.career)

    # Статусы аккаунта (Премиум & Верификация)
    is_prem = user.is_premium
    if is_prem and user.premium_until:
        prem_date = user.premium_until.strftime("%d.%m.%Y")
        premium_str = f"💎 <b>Премиум:</b> Активен до {prem_date} ✅"
        title_name = f"💎 <b>{name}</b> 💎"
        premium_label = " 💎 [Премиум]"
    else:
        premium_str = "💎 <b>Премиум:</b> Не активен"
        title_name = f"<b>{name}</b>"
        premium_label = ""

    if user.email_verified:
        u_name = user.university.short_name if user.university else "РУДН"
        verified_str = f"🎓 <b>Верификация:</b> ✅ Подтверждена ({u_name})"
        verified_badge = f" 🎓 [{u_name}]"
    else:
        verified_str = "🎓 <b>Верификация:</b> ⏳ Не подтверждена (+100⭐)"
        verified_badge = ""

    if is_career_view:
        # Карьерная анкета
        photo_file_id = profile.career_avatar_file_id or profile.avatar_file_id
        skills_text = html.escape(profile.career_custom_skills or "Не указаны")
        goal_text = html.escape(profile.career_goal or "Не указана")
        work_fmt = html.escape(profile.career_work_format or "Не указан")
        portfolio_str = f"\n🔗 <b>Портфолио/Резюме:</b> {html.escape(profile.career_portfolio_url)}" if profile.career_portfolio_url else ""
        status_str = "✅ Заполнена" if profile.career_is_complete else "⚠️ Не заполнена (нажми кнопку ниже)"

        text = (
            f"{title_name}{format_age(profile.age)}{verified_badge}{premium_label}, {year_str} 🎯 <b>[Карьера]</b>\n"
            f"<i>Статус: {status_str}</i>\n\n"
            f"📚 {major}\n"
            f"💼 Формат: {work_fmt}\n"
            f"⭐ Рейтинг: <b>{score_val:.0f} б.</b>\n\n"
            f"🛠 <b>Навыки и стек:</b>\n{skills_text}\n\n"
            f"🎯 <b>Цель / Опыт:</b>\n<i>{goal_text}</i>"
            f"{portfolio_str}\n\n"
            f"{premium_str}\n"
            f"{verified_str}\n"
            f"⭐️ Суперлайков: <b>{user.superlike_balance}</b>\n"
            f"📧 {email_str}"
        )
        current_view_param = "career"
    else:
        # Анкета Знакомств
        photo_file_id = profile.avatar_file_id
        g_str = "👨 Парень" if profile.gender == "male" else ("👩 Девушка" if profile.gender == "female" else "")
        tg_str = "👩 Ищу девушек" if profile.target_gender == "female" else ("👨 Ищу парней" if profile.target_gender == "male" else "✨ Ищу всех")
        gender_info = f"\n{g_str} · {tg_str}" if g_str else ""

        tags_text = ""
        if profile.interest_ids:
            res = await db.execute(select(InterestTag).where(InterestTag.id.in_(profile.interest_ids)))
            tags = res.scalars().all()
            tags_text = " ".join(f"#{html.escape(t.name)}" for t in tags)
        if profile.custom_interests:
            tags_text += f"\n✍️ Свои: {html.escape(profile.custom_interests)}"

        goal_text = html.escape(getattr(profile, "goal", "") or "")
        status_str = "✅ Заполнена" if profile.is_complete else "⚠️ Не заполнена"

        text = (
            f"{title_name}{format_age(profile.age)}{verified_badge}{premium_label}, {year_str} ❤️ <b>[Знакомства]</b>\n"
            f"<i>Статус: {status_str}</i>\n\n"
            f"📚 {major}\n"
            f"⭐ Рейтинг: <b>{score_val:.0f} б.</b>"
            f"{gender_info}\n\n"
            f"💬 <b>О себе:</b>\n<i>{goal_text}</i>\n\n"
            f"{tags_text}\n\n"
            f"{premium_str}\n"
            f"{verified_str}\n"
            f"⭐️ Суперлайков: <b>{user.superlike_balance}</b>\n"
            f"📧 {email_str}"
        )
        current_view_param = "dating"

    reply_kb = my_profile_keyboard(user, current_view=current_view_param)

    from bot.handlers.browse import _get_photo_input
    from aiogram.types import InputMediaPhoto, InputMediaVideo

    if is_career_view:
        # Для карьеры отправляем деловое фото
        photo_input = _get_photo_input(photo_file_id)
        if photo_input:
            try:
                await message.answer_photo(
                    photo=photo_input,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_kb,
                )
                return
            except Exception:
                pass
    else:
        # Для знакомств проверяем всю галерею (до 3 фото + 1 видео)
        photos = list(profile.photos) if profile.photos else ([profile.avatar_file_id] if profile.avatar_file_id else [])
        photos = photos[:3]
        video_id = profile.video_file_id
        total_media_count = len(photos) + (1 if video_id else 0)

        if total_media_count > 1:
            media_group = []
            is_first = True
            for p_id in photos:
                p_input = _get_photo_input(p_id)
                if p_input:
                    if is_first:
                        media_group.append(InputMediaPhoto(media=p_input, caption=text, parse_mode="HTML"))
                        is_first = False
                    else:
                        media_group.append(InputMediaPhoto(media=p_input))

            if video_id:
                v_input = _get_photo_input(video_id)
                if v_input:
                    if is_first:
                        media_group.append(InputMediaVideo(media=v_input, caption=text, parse_mode="HTML"))
                        is_first = False
                    else:
                        media_group.append(InputMediaVideo(media=v_input))

            if media_group:
                try:
                    await message.answer_media_group(media=media_group)
                    await message.answer("👇 <b>Управление профилем:</b>", parse_mode="HTML", reply_markup=reply_kb)
                    return
                except Exception:
                    pass

        if photos:
            p_input = _get_photo_input(photos[0])
            if p_input:
                try:
                    await message.answer_photo(
                        photo=p_input,
                        caption=text,
                        parse_mode="HTML",
                        reply_markup=reply_kb,
                    )
                    return
                except Exception:
                    pass

        if video_id:
            v_input = _get_photo_input(video_id)
            if v_input:
                try:
                    await message.answer_video(
                        video=v_input,
                        caption=text,
                        parse_mode="HTML",
                        reply_markup=reply_kb,
                    )
                    return
                except Exception:
                    pass

    await message.answer(text, parse_mode="HTML", reply_markup=reply_kb)
