"""
Обработчик активации промокодов в боте.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.fsm import PromoState
from bot.services.promo_service import activate_promo_code

router = Router()


@router.message(Command("promo"))
async def cmd_promo(message: Message, state: FSMContext, db: AsyncSession):
    """Команда /promo [КОД]"""
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) > 1:
        code_text = parts[1].strip()
        success, text = await activate_promo_code(db, message.from_user.id, code_text)
        await message.answer(text, parse_mode="HTML")
        await state.clear()
        return

    await state.set_state(PromoState.waiting_promo_code)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="promo:cancel")]]
    )
    await message.answer(
        "🎁 <b>Ввод промокода</b>\n\n"
        "Отправьте промокод в ответном сообщении, чтобы получить суперлайки, буст или баллы рейтинга:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:enter_promo")
async def cb_enter_promo(callback: CallbackQuery, state: FSMContext):
    """Кнопка 'Ввести промокод' из настроек."""
    await state.set_state(PromoState.waiting_promo_code)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="promo:cancel")]]
    )
    await callback.message.answer(
        "🎁 <b>Ввод промокода</b>\n\n"
        "Отправьте промокод сообщением в чат:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "promo:cancel")
async def cb_promo_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Ввод промокода отменён.")
    await callback.answer()


@router.message(PromoState.waiting_promo_code)
async def process_promo_input(message: Message, state: FSMContext, db: AsyncSession):
    code_text = message.text.strip()
    if code_text.startswith("/"):
        await state.clear()
        return

    success, text = await activate_promo_code(db, message.from_user.id, code_text)
    await message.answer(text, parse_mode="HTML")
    await state.clear()
