"""
Настройки: смена режима, видимость анкеты, покупка суперлайков.
"""
import html
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.swipe import (
    settings_keyboard, my_profile_keyboard, mode_keyboard,
    buy_superlike_keyboard, main_menu_keyboard, interests_keyboard, gender_keyboard,
)
from bot.states.fsm import ProfileState
from database.crud import set_user_mode
from database.models import User, ModeEnum, Profile, InterestTag, Swipe
from bot.utils.dynamic_settings import get_dynamic_pricing

router = Router()


@router.message(StateFilter("*"), F.text.in_({"⚙️ Настройки", "Настройки", "/settings"}))
async def show_settings(message: Message, user: User, state: FSMContext = None):
    if state:
        await state.clear()
    is_vis = user.profile.is_visible if user.profile else True
    await message.answer(
        "⚙️ <b>Настройки</b>",
        parse_mode="HTML",
        reply_markup=settings_keyboard(user.mode.value, is_visible=is_vis),
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
    await state.update_data(selected_interests=selected, editing_from_settings=True)
    await state.set_state(ProfileState.waiting_interests)

    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())
    await callback.message.answer(
        "Выбери интересующие теги (без эмодзи):",
        reply_markup=interests_keyboard(tags, selected),
    )


@router.callback_query(F.data == "settings:edit_profile")
async def edit_profile_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.profile import start_profile_creation
    await start_profile_creation(callback.message, state)


@router.callback_query(F.data == "settings:edit_gender")
async def edit_gender_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileState.waiting_gender)
    await callback.answer()
    await callback.message.answer(
        "👫 <b>Выбери твой пол:</b>",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
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
    msg = (
        "👀 <b>Твоя анкета снова отображается в поиске!</b>\nДругие студенты смогут находить тебя при свайпах."
        if new_state
        else "🔒 <b>Твоя анкета скрыта из поиска!</b>\nОна не будет появляться при свайпах, но останется в Зале славы."
    )
    await callback.message.answer(msg, parse_mode="HTML")


@router.callback_query(F.data == "settings:reset_swipes")
@router.message(F.text == "/reset_swipes")
async def reset_user_swipes(event, user: User, db: AsyncSession):
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


@router.callback_query(F.data == "settings:buy")
async def show_buy(callback: CallbackQuery, user: User):
    await callback.answer()
    balance = user.superlike_balance
    pricing = await get_dynamic_pricing()
    p_vip = pricing["price_premium_1m"]
    p_boost = pricing["price_boost_24h"]
    p_sl3 = pricing["price_superlike_3"]
    p_sl10 = pricing["price_superlike_10"]

    await callback.message.answer(
        f"💎 <b>Премиум-подписка — {p_vip} ₽/мес</b>\n\n"
        "❤️ Безлимитное количество лайков\n"
        "👀 Повышенная видимость профиля\n"
        "✨ Выделись! Профиль обретает специальный значок\n\n"
        f"⭐️ <b>Суперлайки — {p_sl3} ₽ (3 шт) / {p_sl10} ₽ (10 шт)</b>\n\n"
        "⭐️ Стань звёздочкой! Твой профиль в разделе «мэтч» будет первым\n"
        "🤍 Суперлайк покажет серьезную заинтересованность в человеке\n"
        "📈 Шанс на мэтч выше в 2-3 раза!\n\n"
        f"🛸 <b>Буст анкеты — {p_boost} ₽/сутки</b>\n\n"
        "📌 Твой профиль в топе 24ч 🗿 Тебя видят чаще\n"
        "Значок 🌪 у аватарки\n\n"
        f"Баланс суперлайков: <b>{balance}</b> ⭐️\n\n"
        "👉 <i>Купить можно ниже (или кнопка ⭐️ под карточкой):</i>",
        parse_mode="HTML",
        reply_markup=buy_superlike_keyboard(pricing),
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

    if is_career_view:
        # Карьерная анкета
        photo_file_id = profile.career_avatar_file_id or profile.avatar_file_id
        skills_text = html.escape(profile.career_custom_skills or "Не указаны")
        goal_text = html.escape(profile.career_goal or "Не указана")
        work_fmt = html.escape(profile.career_work_format or "Не указан")
        portfolio_str = f"\n🔗 <b>Портфолио/Резюме:</b> {html.escape(profile.career_portfolio_url)}" if profile.career_portfolio_url else ""
        status_str = "✅ Заполнена" if profile.career_is_complete else "⚠️ Не заполнена (нажми кнопку ниже)"

        text = (
            f"<b>{name}</b>, {year_str} 🎯 <b>[Карьера]</b>\n"
            f"<i>Статус: {status_str}</i>\n\n"
            f"📚 {major}\n"
            f"💼 Формат: {work_fmt}\n"
            f"⭐ Рейтинг: <b>{score_val:.0f} б.</b>\n\n"
            f"🛠 <b>Навыки и стек:</b>\n{skills_text}\n\n"
            f"🎯 <b>Цель / Опыт:</b>\n<i>{goal_text}</i>"
            f"{portfolio_str}\n\n"
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
            f"<b>{name}</b>, {year_str} ❤️ <b>[Знакомства]</b>\n"
            f"<i>Статус: {status_str}</i>\n\n"
            f"📚 {major}\n"
            f"⭐ Рейтинг: <b>{score_val:.0f} б.</b>"
            f"{gender_info}\n\n"
            f"💬 <b>О себе:</b>\n<i>{goal_text}</i>\n\n"
            f"{tags_text}\n\n"
            f"⭐️ Суперлайков: <b>{user.superlike_balance}</b>\n"
            f"📧 {email_str}"
        )
        current_view_param = "dating"

    reply_kb = my_profile_keyboard(user, current_view=current_view_param)

    from bot.handlers.browse import _get_photo_input
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

    await message.answer(text, parse_mode="HTML", reply_markup=reply_kb)
