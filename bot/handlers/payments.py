"""
Платежи через ЮКассу: создание, ссылка на оплату.
Webhook обрабатывается в web/routers/admin/payments.py
"""
import asyncio
import functools
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yookassa import Configuration, Payment as YKPayment
import uuid

from bot.config import settings
from database.models import User, PaymentProduct, Payment
from database.crud import create_payment
from bot.utils.dynamic_settings import get_dynamic_pricing

router = Router()

# Настройка ЮКассы
Configuration.account_id = settings.YOOKASSA_SHOP_ID
Configuration.secret_key = settings.YOOKASSA_SECRET_KEY


from bot.utils.dynamic_settings import get_dynamic_pricing, get_payment_products_catalog

@router.callback_query(F.data.startswith("buy:"))
async def initiate_payment(callback: CallbackQuery, user: User, db: AsyncSession):
    product_key = callback.data.split(":")[1]
    catalog = await get_payment_products_catalog()
    catalog_map = {p["id"]: p for p in catalog}

    product_item = catalog_map.get(product_key)
    if not product_item or not product_item.get("is_active", True):
        await callback.answer("Этот тариф временно недоступен.", show_alert=True)
        return

    # Подбираем enum PaymentProduct если есть, иначе fallback
    enum_prod = getattr(PaymentProduct, product_key, None) or PaymentProduct.premium_1m
    price_val = float(product_item.get("price", 199))
    label_val = f"{product_item.get('emoji', '💎')} {product_item.get('name', 'Тариф')}"

    product_info = {
        "label": label_val,
        "amount": price_val,
        "product": enum_prod,
    }

    # Создаём запись платежа в БД
    payment = await create_payment(
        db,
        user_id=user.id,
        product=product_info["product"],
        amount_rub=product_info["amount"],
    )

    # Создаём платёж в ЮКассе через executor (синхронный SDK не блокирует event loop)
    payment_data = {
        "amount": {"value": str(product_info["amount"]) + ".00", "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": settings.YOOKASSA_RETURN_URL,
        },
        "capture": True,
        "description": f"СтудМэч: {product_info['label']} (user_id={user.id})",
        "metadata": {
            "payment_id": str(payment.id),
            "user_id": str(user.id),
            "product": product_key,
        },
    }
    idempotency_key = str(payment.id)

    try:
        loop = asyncio.get_event_loop()
        yk_payment = await loop.run_in_executor(
            None,
            functools.partial(YKPayment.create, payment_data, idempotency_key=idempotency_key)
        )
    except Exception:
        await callback.answer("⚠️ Ошибка создания платежа. Попробуй позже.", show_alert=True)
        return

    # Сохраняем YooKassa payment_id в ТОЙ ЖЕ сессии
    await db.execute(
        update(Payment)
        .where(Payment.id == payment.id)
        .values(yookassa_payment_id=yk_payment.id)
    )
    await db.commit()

    confirmation_url = yk_payment.confirmation.confirmation_url

    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить", url=confirmation_url)
    builder.adjust(1)

    await callback.answer()
    await callback.message.answer(
        f"💳 <b>Оплата: {product_info['label']}</b>\n\n"
        f"Сумма: <b>{product_info['amount']} ₽</b>\n\n"
        f"Нажми кнопку ниже для перехода к оплате.\n"
        f"После оплаты товар будет начислен автоматически ✅",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
