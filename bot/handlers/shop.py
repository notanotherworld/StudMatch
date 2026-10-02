"""
Обработчик внутреннего магазина и баланса «Зачётов» 🎓.
"""
import asyncio
import functools
import logging
import os
import uuid
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yookassa import Configuration, Payment as YKPayment

from bot.config import settings
from bot.keyboards.shop import (
    shop_main_keyboard,
    shop_category_keyboard,
    shop_item_detail_keyboard,
    shop_inventory_keyboard,
    deposit_credits_keyboard,
    CREDIT_PACKAGES,
    _category_name,
)
from bot.keyboards.swipe import main_menu_keyboard
from bot.services.economy_service import format_credits, get_frame_title
from database.crud import (
    get_user,
    get_shop_catalog,
    get_shop_item,
    buy_shop_item_with_credits,
    get_user_inventory,
    equip_profile_frame,
    create_payment,
    confirm_payment,
)
from database.models import User, Payment, PaymentProduct

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("shop"))
@router.message(Command("store"))
@router.message(F.text == "🏪 Магазин и Зачётка")
async def cmd_shop_main(message: Message, user: User, db: AsyncSession):
    """Точка входа в магазин из главного меню или по команде /shop."""
    text, keyboard = await _render_shop_main(user, db)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "shop:main")
async def cb_shop_main(callback: CallbackQuery, user: User, db: AsyncSession):
    """Возврат в главное меню магазина из подкатегорий."""
    text, keyboard = await _render_shop_main(user, db)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


async def _render_shop_main(user: User, db: AsyncSession):
    # Обновляем данные пользователя из БД
    u = await get_user(db, user.id) or user
    bal = u.credits_balance or 0
    streak = u.streak_days or 0
    superlikes = u.superlike_balance or 0
    freezes = u.streak_freeze_count or 0
    frame_text = get_frame_title(u.equipped_frame) or "нет"

    text = (
        f"🏪 <b>Магазин привилегий StudMatch</b>\n\n"
        f"Твой баланс: <b>{format_credits(bal)}</b>\n"
        f"🔥 Серия входа (стрик): <b>{streak} дн.</b>\n"
        f"⭐️ Суперлайков в запасе: <b>{superlikes} шт.</b>\n"
        f"🩺 Справок от врача: <b>{freezes} шт.</b>\n"
        f"🖼 Активная рамка: <b>{frame_text}</b>\n\n"
        f"Выбери нужный раздел каталога ниже:"
    )
    keyboard = shop_main_keyboard(bal, streak)
    return text, keyboard


@router.callback_query(F.data.startswith("shop:cat:"))
async def cb_shop_category(callback: CallbackQuery, user: User, db: AsyncSession):
    """Просмотр товаров конкретной категории."""
    category = callback.data.split(":")[2]
    items = await get_shop_catalog(db, category=category, only_active=True)

    cat_title = _category_name(category)
    if not items:
        await callback.answer("В этой категории пока нет товаров.", show_alert=True)
        return

    text = (
        f"🛍 <b>Каталог: {cat_title}</b>\n\n"
        f"Твой текущий баланс: <b>{format_credits(user.credits_balance or 0)}</b>\n\n"
        f"Выбери интересующий товар для подробностей:"
    )
    keyboard = shop_category_keyboard(items, category)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:item:"))
async def cb_shop_item_detail(callback: CallbackQuery, user: User, db: AsyncSession):
    """Детальная карточка товара."""
    item_code = callback.data.split(":")[2]
    item = await get_shop_item(db, item_code)
    if not item or not item.is_active:
        await callback.answer("Товар не найден или отключён.", show_alert=True)
        return

    u = await get_user(db, user.id) or user
    bal = u.credits_balance or 0

    desc = item.description or "Отличный выбор для твоего студенческого профиля!"
    text = (
        f"{item.icon} <b>{item.title}</b>\n\n"
        f"📝 <b>Описание:</b> {desc}\n"
        f"💰 <b>Стоимость:</b> <b>{item.price_credits} 🎓</b>"
    )
    if item.price_rub:
        text += f" (или <b>{item.price_rub} ₽</b> напрямую)"
    if item.duration_days:
        text += f"\n⏳ <b>Срок действия:</b> {item.duration_days} дней"

    text += f"\n\nТвой баланс: <b>{format_credits(bal)}</b>"

    keyboard = shop_item_detail_keyboard(item, bal)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:buy:"))
async def cb_shop_buy_credits(callback: CallbackQuery, user: User, db: AsyncSession):
    """Покупка за внутренние «Зачёты» 🎓."""
    item_code = callback.data.split(":")[2]
    success, msg = await buy_shop_item_with_credits(db, user.id, item_code)

    if not success:
        await callback.answer(msg, show_alert=True)
        return

    # Обновляем пользователя и возвращаемся в главное меню магазина с поздравлением
    u = await get_user(db, user.id) or user
    _, keyboard = await _render_shop_main(u, db)
    await callback.message.edit_text(
        f"{msg}\n\n🏪 <b>Магазин StudMatch</b>",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer("Успешно куплено! ✅")


@router.callback_query(F.data == "shop:inventory")
async def cb_shop_inventory(callback: CallbackQuery, user: User, db: AsyncSession):
    """Просмотр инвентаря пользователя."""
    u = await get_user(db, user.id) or user
    inv = await get_user_inventory(db, user.id)

    text = (
        f"🎒 <b>Твой инвентарь и артефакты</b>\n\n"
        f"🎓 Баланс: <b>{format_credits(u.credits_balance or 0)}</b>\n"
        f"⭐️ Суперлайки: <b>{u.superlike_balance or 0} шт.</b>\n"
        f"🩺 Справки от врача (заморозки стрика): <b>{u.streak_freeze_count or 0} шт.</b>\n"
    )

    rewind_item = next((it for it in inv if it.item_code == "rewind"), None)
    rewind_qty = rewind_item.quantity if rewind_item else 0
    text += f"🔄 «Шпоры» (откаты свайпа): <b>{rewind_qty} шт.</b>\n"

    frame_text = get_frame_title(u.equipped_frame) or "нет"
    text += f"🖼 Надетый статус: <b>{frame_text}</b>\n\n"

    # Список доступных рамок
    frames = [it for it in inv if it.item_code.startswith("frame_")]
    if frames:
        text += "Ты можешь надеть или сменить оформление:"
    else:
        text += "💡 У тебя пока нет статусных рамок. Их можно приобрести в разделе «🎨 Рамки и статусы» магазина."

    keyboard = shop_inventory_keyboard(inv, u.equipped_frame)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:frame:"))
async def cb_shop_frame_action(callback: CallbackQuery, user: User, db: AsyncSession):
    """Надеть/снять рамку."""
    parts = callback.data.split(":")
    action = parts[2]
    frame_code = parts[3] if len(parts) > 3 else None

    if action == "unequip":
        await equip_profile_frame(db, user.id, None)
        await callback.answer("Рамка снята.")
    else:
        success = await equip_profile_frame(db, user.id, frame_code)
        if success:
            await callback.answer("Рамка успешно надета! 🥇")
        else:
            await callback.answer("Не удалось применить рамку.", show_alert=True)

    # Обновляем экран инвентаря
    u = await get_user(db, user.id) or user
    inv = await get_user_inventory(db, user.id)
    keyboard = shop_inventory_keyboard(inv, u.equipped_frame)
    frame_text = get_frame_title(u.equipped_frame) or "нет"
    text = (
        f"🎒 <b>Твой инвентарь и артефакты</b>\n\n"
        f"🎓 Баланс: <b>{format_credits(u.credits_balance or 0)}</b>\n"
        f"🖼 Надетый статус: <b>{frame_text}</b>\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "shop:deposit")
async def cb_shop_deposit(callback: CallbackQuery, user: User):
    """Меню покупки пакетов «Зачётов» за рубли."""
    text = (
        f"💳 <b>Пополнение баланса «Зачётов» 🎓</b>\n\n"
        f"Оплата через ЮКассу (СБП, Тинькофф, SberPay, банковские карты РФ).\n"
        f"Зачёты зачисляются на аккаунт моментально после успешной оплаты!\n\n"
        f"Выбери выгодный пакет:"
    )
    keyboard = deposit_credits_keyboard(has_bought_starter_pack=bool(user.has_bought_starter_pack))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "shop:starter_already_bought")
async def cb_shop_starter_already_bought(callback: CallbackQuery):
    """Уведомление о том, что стартовый набор уже куплен."""
    await callback.answer("⚠️ Стартовый набор первокурсника уже был приобретён. Он доступен только 1 раз на аккаунт!", show_alert=True)


@router.callback_query(F.data.startswith("shop:deposit_pack:"))
async def cb_shop_deposit_pack(callback: CallbackQuery, user: User, db: AsyncSession):
    """Создание ссылки на оплату пакета зачётов в ЮКассе."""
    pack_code = callback.data.split(":")[2]
    pack = next((p for p in CREDIT_PACKAGES if p["code"] == pack_code), None)
    if not pack:
        await callback.answer("Пакет не найден.", show_alert=True)
        return

    if pack_code == "starter_pack_99" and user.has_bought_starter_pack:
        await callback.answer("⚠️ Стартовый набор доступен только 1 раз на аккаунт и уже был куплен!", show_alert=True)
        return

    # Подбираем enum PaymentProduct
    prod_enum = getattr(PaymentProduct, pack_code, None) or (
        PaymentProduct.starter_pack_99 if pack_code == "starter_pack_99" else PaymentProduct.premium_1m
    )

    # Создаём платежную запись
    payment = await create_payment(
        db,
        user_id=user.id,
        product=prod_enum,
        amount_rub=float(pack["price"]),
    )

    has_yk = bool(
        getattr(settings, "YOOKASSA_SHOP_ID", None)
        and getattr(settings, "YOOKASSA_SECRET_KEY", None)
        and str(settings.YOOKASSA_SHOP_ID).strip() != ""
        and str(settings.YOOKASSA_SECRET_KEY).strip() != ""
    )

    is_dev_or_test = (
        getattr(settings, "DEBUG", False)
        or os.getenv("DEBUG", "false").lower() == "true"
        or os.getenv("TESTING") == "true"
        or str(settings.DATABASE_URL).startswith("sqlite")
    )

    if has_yk:
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

        payment_data = {
            "amount": {"value": f"{pack['price']}.00", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": settings.YOOKASSA_RETURN_URL,
            },
            "capture": True,
            "description": f"StudMatch: {pack['title']} (user_id={user.id})",
            "metadata": {
                "payment_id": str(payment.id),
                "user_id": str(user.id),
                "product": pack_code,
            },
        }

        try:
            loop = asyncio.get_event_loop()
            yk_payment = await loop.run_in_executor(
                None,
                functools.partial(YKPayment.create, payment_data, idempotency_key=str(payment.id)),
            )
        except Exception as e:
            logger.error(f"Error creating YooKassa payment for credits pack: {e}", exc_info=True)
            await callback.answer("⚠️ Ошибка создания платежа. Попробуй позже.", show_alert=True)
            return

        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(yookassa_payment_id=yk_payment.id)
        )
        await db.commit()

        confirmation_url = yk_payment.confirmation.confirmation_url
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Перейти к оплате", url=confirmation_url)
        builder.button(text="◀️ В магазин", callback_data="shop:main")
        builder.adjust(1)

        await callback.message.edit_text(
            f"💳 <b>Пополнение баланса</b>\n\n"
            f"Пакет: <b>{pack['title']}</b>\n"
            f"К оплате: <b>{pack['price']} ₽</b>\n\n"
            f"После оплаты «Зачёты» будут начислены на твой баланс автоматически! ✅",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    if is_dev_or_test:
        test_yk_id = f"demo_yk_{payment.id}"
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(yookassa_payment_id=test_yk_id)
        )
        await db.commit()

        await confirm_payment(db, test_yk_id)

        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ В магазин", callback_data="shop:main")
        builder.adjust(1)

        await callback.message.edit_text(
            f"🎉 <b>[Тестовый режим] Пакет успешно начислен!</b>\n\n"
            f"Пакет: <b>{pack['title']}</b> ({pack['price']} ₽)\n"
            f"«Зачёты» и бонусы уже зачислены на твой аккаунт! ✅",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        await callback.answer("🛠 [Dev Mode] Начислено!", show_alert=False)
        return

    logger.error(f"[SECURITY] YooKassa is not configured in production, rejecting credits pack payment {pack_code}")
    await callback.answer("⚠️ Платежи временно недоступны.", show_alert=True)


@router.callback_query(F.data.startswith("shop:buy_rub:"))
async def cb_shop_buy_rub(callback: CallbackQuery, user: User, db: AsyncSession):
    """Прямая покупка товара за рубли через ЮКассу."""
    item_code = callback.data.split(":")[2]
    item = await get_shop_item(db, item_code)
    if not item or not item.price_rub:
        await callback.answer("Прямая покупка за рубли недоступна для этого товара.", show_alert=True)
        return

    # Перенаправляем на существующий механизм оплаты тарифов
    payment = await create_payment(
        db,
        user_id=user.id,
        product=getattr(PaymentProduct, item_code, PaymentProduct.premium_1m),
        amount_rub=float(item.price_rub),
    )

    has_yk = bool(
        getattr(settings, "YOOKASSA_SHOP_ID", None)
        and getattr(settings, "YOOKASSA_SECRET_KEY", None)
        and str(settings.YOOKASSA_SHOP_ID).strip() != ""
        and str(settings.YOOKASSA_SECRET_KEY).strip() != ""
    )

    is_dev_or_test = (
        getattr(settings, "DEBUG", False)
        or os.getenv("DEBUG", "false").lower() == "true"
        or os.getenv("TESTING") == "true"
        or str(settings.DATABASE_URL).startswith("sqlite")
    )

    if has_yk:
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

        payment_data = {
            "amount": {"value": f"{item.price_rub}.00", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": settings.YOOKASSA_RETURN_URL,
            },
            "capture": True,
            "description": f"StudMatch: {item.title} (user_id={user.id})",
            "metadata": {
                "payment_id": str(payment.id),
                "user_id": str(user.id),
                "product": item_code,
            },
        }

        try:
            loop = asyncio.get_event_loop()
            yk_payment = await loop.run_in_executor(
                None,
                functools.partial(YKPayment.create, payment_data, idempotency_key=str(payment.id)),
            )
        except Exception as e:
            logger.error(f"Error creating YooKassa payment: {e}", exc_info=True)
            await callback.answer("⚠️ Ошибка создания платежа.", show_alert=True)
            return

        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(yookassa_payment_id=yk_payment.id)
        )
        await db.commit()

        confirmation_url = yk_payment.confirmation.confirmation_url
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Оплатить картой / СБП", url=confirmation_url)
        builder.button(text="◀️ В магазин", callback_data="shop:main")
        builder.adjust(1)

        await callback.message.edit_text(
            f"💳 <b>Оплата услуги: {item.title}</b>\n\n"
            f"Сумма: <b>{item.price_rub} ₽</b>\n\n"
            f"Нажми кнопку ниже для безопасной оплаты:",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    if is_dev_or_test:
        test_yk_id = f"demo_yk_{payment.id}"
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(yookassa_payment_id=test_yk_id)
        )
        await db.commit()

        await confirm_payment(db, test_yk_id)

        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ В магазин", callback_data="shop:main")
        builder.adjust(1)

        await callback.message.edit_text(
            f"🎉 <b>[Тестовый режим] Услуга успешно активирована!</b>\n\n"
            f"Товар: <b>{item.title}</b> ({item.price_rub} ₽)\n"
            f"Услуга подключена к твоему профилю! ✅",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        await callback.answer("🛠 [Dev Mode] Успешно!", show_alert=False)
        return

    logger.error(f"[SECURITY] YooKassa is not configured in production, rejecting rub payment {item_code}")
    await callback.answer("⚠️ Платежи временно недоступны.", show_alert=True)


@router.callback_query(F.data == "shop:back_to_main")
async def cb_shop_back_to_main(callback: CallbackQuery):
    """Выход в главное меню Telegram бота."""
    await callback.message.delete()
    await callback.message.answer(
        "📋 <b>Главное меню:</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()
