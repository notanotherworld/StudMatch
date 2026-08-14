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

from bot.keyboards.swipe import settings_keyboard, my_profile_keyboard, mode_keyboard, buy_superlike_keyboard, main_menu_keyboard
from bot.states.fsm import ProfileState
from database.crud import set_user_mode
from database.models import User, ModeEnum, Profile, InterestTag, Swipe

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
    if not user.profile:
        await callback.answer("Сначала заполни анкету!")
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


@router.callback_query(F.data == "settings:edit_gender")
async def edit_gender_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileState.waiting_gender)
    await callback.answer()
    from bot.keyboards.swipe import gender_keyboard
    await callback.message.answer(
        "👫 <b>Выбери твой пол:</b>",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
    )

    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())

    await callback.answer()
    await callback.message.answer(
        "🏷 <b>Редактирование интересов</b>\n\n"
        "Нажимай на теги, чтобы <b>добавить</b> или <b>удалить</b> их из анкеты.\n"
        "По окончании нажми <b>✔️ Готово</b>:",
        parse_mode="HTML",
        reply_markup=interests_keyboard(tags, selected),
    )


@router.callback_query(F.data.startswith("mode:"))
async def set_mode(callback: CallbackQuery, user: User, db: AsyncSession):
    mode_str = callback.data.split(":")[1]
    mode = ModeEnum.career if mode_str == "career" else ModeEnum.dating
    await set_user_mode(db, user.id, mode)

    label = "🎯 Карьера" if mode == ModeEnum.career else "❤️ Знакомства"
    extra_text = (
        "\n\n💼 <i>Компании видят топ-50. Чем выше ты в этом списке, тем чаще они пишут тебе первыми. Все получится 🤲🏻</i>"
        if mode == ModeEnum.career else ""
    )
    await callback.answer(f"Режим изменён: {label}")
    await callback.message.edit_reply_markup(reply_markup=None)
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
        "Теперь нажми <b>🏆 Топ студентов</b> в меню, чтобы просмотреть все 10 тестовых анкет заново."
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
    await callback.message.answer(
        "💎 <b>Премиум-подписка — 199 ₽/мес</b>\n\n"
        "❤️ Безлимитное количество лайков\n"
        "👀 Повышенная видимость профиля\n"
        "✨ Выделись! Профиль обретает специальный значок\n\n"
        "❤️🔥 <b>Суперлайк — 49 ₽ (3 шт) / 99 ₽ (5 шт)</b>\n\n"
        "⭐️ Стань звёздочкой! Твой профиль в разделе «мэтч» будет первым\n"
        "🤍 Суперлайк покажет серьезную заинтересованность в человеке\n"
        "📈 Шанс на мэтч выше в 2-3 раза!\n\n"
        "🛸 <b>Буст — 99 ₽/сутки</b>\n\n"
        "📌 Твой профиль в топе 24ч 🗿 Тебя видят чаще\n"
        "Значок 🌪 у аватарки\n\n"
        f"Баланс суперлайков: <b>{balance}</b> ⭐️\n\n"
        "👉 <i>Купить можно ниже (или кнопка ⭐️ под карточкой):</i>",
        parse_mode="HTML",
        reply_markup=buy_superlike_keyboard(),
    )


@router.message(StateFilter("*"), F.text.func(lambda t: bool(t and ("Пригласить" in t or "ref" in t.lower()))))
@router.callback_query(F.data == "settings:ref_link")
async def show_referral_link(event, user: User, state: FSMContext = None):
    if state:
        await state.clear()
    bot_info = await event.bot.get_me()
    ref_url = f"https://t.me/{bot_info.username}?start=ref_{user.id}"

    text = (
        f"🔗 <b>Приглашай друзей в СтудМэч!</b>\n\n"
        f"Отправь другу свою персональную ссылку:\n"
        f"<code>{ref_url}</code>\n\n"
        f"🎁 За каждого зарегистрировавшегося друга ты получаешь <b>+3 ⭐️ Суперлайка</b>!"
    )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="HTML")
    else:
        await event.answer(text, parse_mode="HTML")


@router.message(StateFilter("*"), F.text.in_({"🐾 Мой профиль", "👤 Мой профиль", "Мой профиль", "/profile"}))
async def show_my_profile(message: Message, user: User, db: AsyncSession, state: FSMContext = None):
    if state:
        await state.clear()
    profile = user.profile
    if not profile or not profile.is_complete:
        await message.answer("У тебя ещё нет анкеты. Напиши /start чтобы создать.")
        return

    mode_label = "🎯 Карьера" if user.mode == ModeEnum.career else "❤️ Знакомства"
    visibility = "👀 В поиске (свайпах)" if profile.is_visible else "🔒 Скрыта из поиска"

    g_str = "👨 Парень" if profile.gender == "male" else ("👩 Девушка" if profile.gender == "female" else "")
    tg_str = "👩 Ищу девушек" if profile.target_gender == "female" else ("👨 Ищу парней" if profile.target_gender == "male" else "✨ Ищу всех")
    gender_info = f"\n{g_str} · {tg_str}" if g_str else ""

    # Кастомные интересы в профиле (#14)
    custom_block = ""
    if profile.custom_interests:
        custom_block = f"\n✍️ Свои: <i>{html.escape(profile.custom_interests)}</i>"

    email_str = html.escape(user.email or "не указан")
    score_val = profile.rating_score or 0.0
    year_str = f"{profile.year} курс" if profile.year else "Студент"

    text = (
        f"<b>{html.escape(profile.name or 'Студент')}</b>, {year_str}\n\n"
        f"📚 {html.escape(profile.major or '')}\n\n"
        f"{mode_label} · ⭐ {score_val:.0f} б."
        f"{gender_info}\n"
        f"{visibility}\n\n"
        f"💬 <i>{html.escape(getattr(profile, 'goal', '') or '')}</i>\n"
        f"{custom_block}\n\n"
        f"⭐ Суперлайков: <b>{user.superlike_balance}</b>\n"
        f"📧 {email_str}"
    )

    if profile.avatar_file_id:
        try:
            await message.answer_photo(
                photo=profile.avatar_file_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=my_profile_keyboard(user.mode.value),
            )
            return
        except Exception:
            pass

    await message.answer(text, parse_mode="HTML", reply_markup=my_profile_keyboard(user.mode.value))
