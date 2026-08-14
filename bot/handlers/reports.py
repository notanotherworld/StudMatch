"""
#8 Жалобы: студент жалуется на другого через бота.
#10 Запрос на выгрузку персональных данных (ФЗ-152).
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.states.fsm import ReportState
from database.models import User, Report, ReportStatus, DataExportRequest

router = Router()

REPORT_REASONS = [
    ("spam",        "📢 Спам / реклама"),
    ("fake",        "🎭 Фейковый профиль"),
    ("insult",      "🤬 Оскорбления"),
    ("adult",       "🔞 18+ контент"),
    ("other",       "❓ Другое"),
]


# ─── Жалоба через кнопку на карточке ────────────────────────────────────────
@router.callback_query(F.data.startswith("report:"))
async def start_report(callback: CallbackQuery, user: User, state: FSMContext):
    target_id = int(callback.data.split(":")[1])
    await state.clear()
    await callback.answer()

    builder = InlineKeyboardBuilder()
    for key, label in REPORT_REASONS:
        builder.button(text=label, callback_data=f"report_reason:{key}:{target_id}")
    builder.button(text="✕ Отмена", callback_data=f"report_cancel:{target_id}")
    builder.adjust(1)

    await callback.message.answer(
        "⚠️ <b>Пожаловаться на пользователя</b>\n\n"
        "Укажи причину жалобы:",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("report_reason:"))
async def finish_report(callback: CallbackQuery, user: User, state: FSMContext, db: AsyncSession):
    parts = callback.data.split(":")
    reason_key = parts[1]
    target_id = int(parts[2]) if len(parts) > 2 else None

    if not target_id:
        data = await state.get_data()
        target_id = data.get("report_target_id")

    await state.clear()

    if not target_id or target_id == user.id:
        await callback.answer("Ошибка!", show_alert=True)
        return

    reason_label = dict(REPORT_REASONS).get(reason_key, reason_key)

    # Проверяем, не жаловался ли уже
    existing = await db.execute(
        select(Report).where(Report.reporter_id == user.id, Report.reported_id == target_id)
    )
    if not existing.scalar_one_or_none():
        report = Report(
            reporter_id=user.id,
            reported_id=target_id,
            reason=reason_label,
            status=ReportStatus.pending,
        )
        db.add(report)
        await db.commit()

    # Скрываем пользователя из ленты (скипаем)
    try:
        await create_swipe(db, from_id=user.id, to_id=target_id, action=SwipeAction.dislike)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error recording report skip swipe: {e}", exc_info=True)

    await callback.answer("✅ Жалоба отправлена!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)

    # Авто-показ следующей анкеты
    from bot.handlers.browse import send_next_card
    await send_next_card(callback.bot, callback.from_user.id, user, db)


@router.callback_query(F.data.startswith("report_cancel"))
async def cancel_report(callback: CallbackQuery, user: User, state: FSMContext, db: AsyncSession):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)

    from bot.handlers.browse import send_next_card
    await send_next_card(callback.bot, callback.from_user.id, user, db)


# ─── #10: Запрос на выгрузку данных ─────────────────────────────────────────
@router.message(F.text.in_(["📥 Мои данные", "/mydata"]))
async def request_data_export(message: Message, user: User, db: AsyncSession):
    # Проверяем, нет ли уже активного запроса
    existing = await db.execute(
        select(DataExportRequest).where(
            DataExportRequest.user_id == user.id,
            DataExportRequest.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        await message.answer(
            "⏳ <b>Запрос уже в очереди</b>\n\n"
            "Модератор обработает его в ближайшее время и пришлёт файл сюда.",
            parse_mode="HTML",
        )
        return

    req = DataExportRequest(user_id=user.id)
    db.add(req)
    await db.commit()

    await message.answer(
        "📥 <b>Запрос на выгрузку данных принят</b>\n\n"
        "Мы подготовим файл с твоими персональными данными "
        "в соответствии с ФЗ-152 «О персональных данных».\n\n"
        "⏳ Обычно это занимает до <b>3 рабочих дней</b>.\n"
        "Файл придёт прямо сюда.",
        parse_mode="HTML",
    )
