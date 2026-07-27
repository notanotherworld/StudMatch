"""
Настройки: смена режима, видимость анкеты, покупка суперлайков.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from bot.keyboards.swipe import settings_keyboard, mode_keyboard, buy_superlike_keyboard, main_menu_keyboard
from database.crud import set_user_mode
from database.models import User, ModeEnum, Profile

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
    await callback.answer(f"Анкета {label}!")
    await callback.message.answer(
        f"👁 Твоя анкета теперь <b>{label}</b> в топе.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:buy")
async def show_buy(callback: CallbackQuery, user: User):
    await callback.answer()
    balance = user.superlike_balance
    await callback.message.answer(
        f"💎 <b>Премиум — 299 ₽/мес</b>\n"
        f"1. Безлимитные лайки\n"
        f"2. Тебя видят чаще\n"
        f"3. Выделись! Твой профиль помечается значком 💎\n\n"
        f"⭐️ <b>Суперлайк — 49 ₽ (1 шт) / 99 ₽ (3 шт)</b>\n"
        f"1. Твой профиль будет первым\n"
        f"2. Суперлайк покажет серьезную заинтересованность в человеке\n"
        f"3. Шанс на мэтч выше в 2-3 раза\n\n"
        f"Текущий баланс: <b>{balance}</b> ⭐ суперлайков\n\n"
        f"👉 <i>Купить можно ниже:</i>",
        parse_mode="HTML",
        reply_markup=buy_superlike_keyboard(),
    )


@router.message(F.text == "👤 Мой профиль")
async def show_my_profile(message: Message, user: User, db: AsyncSession):
    profile = user.profile
    if not profile or not profile.is_complete:
        await message.answer("У тебя ещё нет анкеты. Напиши /start чтобы создать.")
        return

    mode_label = "🎯 Карьера" if user.mode == ModeEnum.career else "❤️ Знакомства"
    visibility = "👁 Видна в топе" if profile.is_visible else "🔒 Скрыта"

    text = (
        f"👤 <b>Мой профиль</b>\n\n"
        f"<b>{profile.name}</b>, {profile.year} курс\n"
        f"📚 {profile.major}\n"
        f"{mode_label} · ⭐ {profile.rating_score:.0f} б.\n"
        f"{visibility}\n\n"
        f"💬 <i>{profile.goal}</i>\n\n"
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
