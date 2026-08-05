"""
Настройки: смена режима, видимость анкеты, покупка суперлайков.
"""
import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.swipe import settings_keyboard, mode_keyboard, buy_superlike_keyboard, main_menu_keyboard
from bot.states.fsm import ProfileState
from database.crud import set_user_mode
from database.models import User, ModeEnum, Profile, InterestTag, Swipe

router = Router()


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message, user: User):
    await message.answer(
        "⚙️ <b>Настройки</b>",
        parse_mode="HTML",
        reply_markup=settings_keyboard(user.mode.value),
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

    from sqlalchemy import select
    from database.models import InterestTag
    from bot.keyboards.swipe import interests_keyboard

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
    await callback.answer(f"Режим изменён: {label}")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Режим изменён на <b>{label}</b>",
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

    label = "видна" if new_state else "скрыта"
    await callback.answer(f"Твоя анкета {label}!")
    msg = (
        "👀 <b>Твоя анкета снова видна в Топе!</b>\nДругие студенты смогут находить тебя и ставить лайки."
        if new_state
        else "🔒 <b>Твоя анкета скрыта из поиска!</b>\nДругие студенты больше не смогут видеть твою анкету в Топе."
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
        f"💎 <b>Премиум-подписка — 199 ₽/мес</b>\n\n"
        f"❤️ Безлимитное количество лайков\n"
        f"👀 Повышенная видимость профиля\n"
        f"✨ Выделись! Профиль обретает специальный значок\n\n"
        f"⭐️ <b>Суперлайк — 49 ₽ (3 шт) / 99 ₽ (5 шт)</b>\n\n"
        f"🌟 Стань звёздочкой! Твой профиль будет первым\n"
        f"🤍 Суперлайк покажет серьезную заинтересованность в человеке\n"
        f"📈 Шанс на мэтч выше в 2-3 раза\n\n"
        f"Текущий баланс: <b>{balance}</b> ⭐ суперлайков\n\n"
        f"👉 <i>Купить можно ниже:</i>",
        parse_mode="HTML",
        reply_markup=buy_superlike_keyboard(),
    )


@router.message(F.text == "🔗 Пригласить друга (+1 ⭐️)")
@router.callback_query(F.data == "settings:ref_link")
async def show_referral_link(event, user: User):
    bot_info = await event.bot.get_me()
    ref_url = f"https://t.me/{bot_info.username}?start=ref_{user.id}"

    text = (
        f"🔗 <b>Приглашай друзей в СтудМэч!</b>\n\n"
        f"Отправь другу свою персональную ссылку:\n"
        f"<code>{ref_url}</code>\n\n"
        f"🎁 За каждого зарегистрировавшегося друга ты получаешь <b>+1 ⭐️ Суперлайк</b>!"
    )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="HTML")
    else:
        await event.answer(text, parse_mode="HTML")


@router.message(F.text == "👤 Мой профиль")
async def show_my_profile(message: Message, user: User, db: AsyncSession):
    profile = user.profile
    if not profile or not profile.is_complete:
        await message.answer("У тебя ещё нет анкеты. Напиши /start чтобы создать.")
        return

    mode_label = "🎯 Карьера" if user.mode == ModeEnum.career else "❤️ Знакомства"
    visibility = "👀 Видна в топе" if profile.is_visible else "🔒 Скрыта"

    # Кастомные интересы в профиле (#14)
    custom_block = ""
    if profile.custom_interests:
        custom_block = f"\n✍️ Свои: <i>{html.escape(profile.custom_interests)}</i>"

    text = (
        f"<b>{html.escape(profile.name or '')}</b>, {profile.year} курс\n"
        f"📚 {html.escape(profile.major or '')}\n"
        f"{mode_label} · ⭐ {profile.rating_score:.0f} б.\n"
        f"{visibility}\n\n"
        f"💬 <i>{html.escape(profile.goal or '')}</i>\n"
        f"{custom_block}\n\n"
        f"⭐ Суперлайков: <b>{user.superlike_balance}</b>\n"
        f"📧 {user.email}"
    )

    if profile.avatar_file_id:
        await message.answer_photo(
            photo=profile.avatar_file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=settings_keyboard(user.mode.value),
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=settings_keyboard(user.mode.value))
