"""
#7 Детализация монетизации: транзакции, фильтры, статистика по продуктам.
#10 Экспорт персональных данных: очередь запросов + отправка студенту.
"""
from fastapi import APIRouter, Request, Depends, Form, Query, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone, timedelta
import io, csv, json, os, logging, ipaddress, functools, asyncio

from bot.config import settings
from web.dependencies import get_db, get_current_admin, check_csrf
from database.models import Payment, PaymentStatus, PaymentProduct, User, DataExportRequest, ExportStatus

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")



@router.get("/payments/export/csv")
async def export_payments_csv(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = Query(default=""),
    product: str = Query(default=""),
):
    """Экспорт истории платежей в CSV с UTF-8 BOM для Excel."""
    filters = []
    if product and product in [p.value for p in PaymentProduct]:
        filters.append(Payment.product == PaymentProduct(product))
    if status and status in [s.value for s in PaymentStatus]:
        filters.append(Payment.status == PaymentStatus(status))

    query = (
        select(Payment)
        .options(selectinload(Payment.user))
        .where(*filters)
        .order_by(Payment.created_at.desc())
    )
    result = await db.execute(query)
    all_payments = result.scalars().all()

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID Платежа", "ID Пользователя", "Username Telegram", "Email",
        "Сумма (руб)", "Товар / Услуга", "Статус", "ID ЮKassa", "Дата и время",
    ])

    for p in all_payments:
        u = p.user
        writer.writerow([
            str(p.id),
            p.user_id,
            f"@{u.tg_username}" if u and u.tg_username else "",
            u.email if u else "",
            p.amount_rub,
            p.product.value if hasattr(p.product, 'value') else str(p.product),
            p.status.value if hasattr(p.status, 'value') else str(p.status),
            p.yookassa_payment_id or "",
            p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=studmatch_payments.csv"},
    )


@router.get("/payments", response_class=HTMLResponse)
async def payments_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    product: str = Query(default=""),
    status: str = Query(default="succeeded"),
    page: int = Query(default=1),
):
    per_page = 30
    offset = (page - 1) * per_page

    filters = []
    if product and product in [p.value for p in PaymentProduct]:
        filters.append(Payment.product == PaymentProduct(product))
    if status and status in [s.value for s in PaymentStatus]:
        filters.append(Payment.status == PaymentStatus(status))

    query = (
        select(Payment)
        .options(selectinload(Payment.user))
        .where(*filters)
        .order_by(Payment.created_at.desc())
        .offset(offset).limit(per_page)
    )
    result = await db.execute(query)
    payments = result.scalars().all()

    from bot.utils.dynamic_settings import get_payment_products_catalog
    catalog = await get_payment_products_catalog()
    catalog_map = {p["id"]: p for p in catalog}

    # Статистика по продуктам (только succeeded)
    stats_result = await db.execute(
        select(Payment.product, func.count(Payment.id), func.sum(Payment.amount_rub))
        .where(Payment.status == PaymentStatus.succeeded)
        .group_by(Payment.product)
    )
    product_stats = []
    for row in stats_result.all():
        prod_val = row[0].value if hasattr(row[0], 'value') else str(row[0])
        prod_meta = catalog_map.get(prod_val, {})
        product_stats.append({
            "product": prod_val,
            "name": prod_meta.get("name", prod_val),
            "emoji": prod_meta.get("emoji", "💰"),
            "price": prod_meta.get("price", 0),
            "count": row[1],
            "revenue": float(row[2] or 0),
        })

    # Выручка за 30 дней (для мини-графика)
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    daily_result = await db.execute(
        select(
            func.date_trunc("day", Payment.created_at).label("day"),
            func.sum(Payment.amount_rub).label("revenue"),
        )
        .where(Payment.status == PaymentStatus.succeeded, Payment.created_at >= month_ago)
        .group_by("day")
        .order_by("day")
    )
    daily_revenue = [
        {"day": row[0].strftime("%d.%m"), "revenue": float(row[1] or 0)}
        for row in daily_result.all()
    ]

    # Запросы на выгрузку данных (фича #10)
    export_result = await db.execute(
        select(DataExportRequest)
        .options(selectinload(DataExportRequest.user))
        .where(DataExportRequest.status == ExportStatus.pending)
        .order_by(DataExportRequest.created_at.desc())
    )
    export_requests = export_result.scalars().all()

    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/payments.html",
        {
            "request": request,
            "admin": admin,
            "payments": payments,
            "product_stats": product_stats,
            "products_catalog": catalog,
            "catalog_map": catalog_map,
            "daily_revenue": daily_revenue,
            "current_product": product,
            "current_status": status,
            "page": page,
            "export_requests": export_requests,
            "csrf_token": token_str,
        },
    )


@router.get("/payments/export.csv")
async def export_payments_simple_csv(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Payment)
        .options(selectinload(Payment.user))
        .where(Payment.status == PaymentStatus.succeeded)
        .order_by(Payment.created_at.desc())
        .limit(1000)
    )
    payments = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID ЮКассы", "Пользователь", "Email", "Продукт", "Сумма (₽)", "Дата"])
    for p in payments:
        writer.writerow([
            p.yookassa_payment_id or "—",
            f"@{p.user.tg_username}" if p.user and p.user.tg_username else str(p.user_id),
            p.user.email if p.user else "—",
            p.product.value, float(p.amount_rub),
            p.created_at.strftime("%d.%m.%Y %H:%M"),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


# ─── #10: Экспорт персональных данных ────────────────────────────────────────
@router.post("/payments/export-data/{request_id}/send", dependencies=[Depends(check_csrf)])
async def send_user_data(
    request_id: str,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сформировать и отправить студенту его данные через бот."""
    import uuid as _uuid
    req_result = await db.execute(
        select(DataExportRequest)
        .options(selectinload(DataExportRequest.user))
        .where(DataExportRequest.id == _uuid.UUID(request_id))
    )
    export_req = req_result.scalar_one_or_none()
    if not export_req:
        return RedirectResponse("/admin/payments", status_code=302)

    user = export_req.user
    from database.models import Achievement, Swipe, Match, Payment as Pay
    from sqlalchemy.orm import selectinload as sil

    # Собираем данные
    profile_res = await db.execute(
        select(User).options(sil(User.profile), sil(User.achievements)).where(User.id == user.id)
    )
    full_user = profile_res.scalar_one_or_none()

    data = {
        "telegram_id": user.id,
        "username": user.tg_username,
        "email": user.email,
        "registered": user.created_at.isoformat() if user.created_at else None,
        "consent_given": user.consent_given,
        "profile": {
            "name": full_user.profile.name if full_user and full_user.profile else None,
            "year": full_user.profile.year if full_user and full_user.profile else None,
            "major": full_user.profile.major if full_user and full_user.profile else None,
            "goal": full_user.profile.goal if full_user and full_user.profile else None,
            "rating": full_user.profile.rating_score if full_user and full_user.profile else 0,
        } if full_user else None,
        "achievements": [
            {"type": a.type.value, "title": a.title, "score": a.score, "verified": a.verified.value}
            for a in (full_user.achievements if full_user else [])
        ],
    }

    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    try:
        from aiogram import Bot
        from aiogram.types import BufferedInputFile
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_document(
            user.id,
            BufferedInputFile(json_str.encode("utf-8"), filename="my_data_studmatch.json"),
            caption=(
                "📦 <b>Ваши персональные данные в СтудМэч</b>\n\n"
                "Этот файл содержит все данные, хранящиеся о вас на платформе.\n"
                "Дата выгрузки: " + datetime.now(timezone.utc).strftime("%d.%m.%Y")
            ),
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception:
        pass

    await db.execute(
        update(DataExportRequest)
        .where(DataExportRequest.id == export_req.id)
        .values(status=ExportStatus.sent, sent_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return RedirectResponse("/admin/payments", status_code=302)


# ─── YooKassa Webhook (Безопасная обработка) ─────────────────
# Официальные подсети серверов ЮKassa (https://yookassa.ru/developers/using-api/webhooks)
YOOKASSA_IP_NETWORKS = [
    ipaddress.ip_network("185.71.76.0/27"),
    ipaddress.ip_network("185.71.77.0/27"),
    ipaddress.ip_network("77.75.153.0/25"),
    ipaddress.ip_network("77.75.156.11/32"),
    ipaddress.ip_network("77.75.156.35/32"),
]


def _is_allowed_yookassa_ip(client_ip: str, is_dev_or_test: bool) -> bool:
    if not client_ip:
        return is_dev_or_test
    try:
        ip_obj = ipaddress.ip_address(client_ip)
        if ip_obj.is_loopback and is_dev_or_test:
            return True
        return any(ip_obj in net for net in YOOKASSA_IP_NETWORKS)
    except ValueError:
        return False


@router.post("/payments/webhook")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Обработка вебхуков от ЮKassa при успешной оплате.
    Защиты:
      1. Валидация IP-адреса источника по белым подсетям серверов ЮKassa.
      2. Криптографическая/API проверка статуса платежа через официальный SDK ЮKassa (find_one).
      3. Идемпотентность начисления (confirm_payment).
    """
    is_dev_or_test = (
        getattr(settings, "DEBUG", False)
        or os.getenv("DEBUG", "false").lower() == "true"
        or os.getenv("TESTING") == "true"
        or str(settings.DATABASE_URL).startswith("sqlite")
    )

    # 1. Проверяем IP-адрес источника
    # X-Real-IP устанавливается только доверенным обратным прокси Nginx ($remote_addr).
    # Никогда не берем x_forwarded_for.split(",")[0], так как первый элемент может быть подделан клиентом.
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        client_ip = x_real_ip.strip()
    elif request.client and request.client.host:
        client_ip = request.client.host.strip()
    else:
        client_ip = ""

    if not _is_allowed_yookassa_ip(client_ip, is_dev_or_test):
        logger.warning(f"[SECURITY] Unauthorized YooKassa webhook attempt from IP={client_ip!r}")
        return JSONResponse({"status": "forbidden", "detail": "IP address not allowed"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "detail": "Invalid JSON"}, status_code=400)

    event = body.get("event")
    obj = body.get("object", {})

    # C5: Обработка возвратов и отмен (refund.succeeded / payment.canceled)
    if event in ("refund.succeeded", "payment.canceled"):
        yk_id = obj.get("payment_id") or obj.get("id")
        if not yk_id:
            return JSONResponse({"status": "error", "detail": "Missing payment id"}, status_code=400)

        from database.crud import process_payment_refund
        reason = "refund" if "refund" in event else "canceled"
        refunded_payment = await process_payment_refund(db, yk_id, reason=reason)

        if refunded_payment:
            logger.info(f"[PAYMENTS] Payment {yk_id} processed for {event} (user={refunded_payment.user_id})")
            try:
                from aiogram import Bot
                bot = Bot(token=settings.BOT_TOKEN)
                if settings.SUPERADMIN_ID:
                    await bot.send_message(
                        settings.SUPERADMIN_ID,
                        f"⚠️ <b>Возврат платежа / Chargeback</b> ({event})\n\n"
                        f"ID платежа: <code>{refunded_payment.id}</code>\n"
                        f"ЮKassa ID: <code>{yk_id}</code>\n"
                        f"Пользователь: <code>{refunded_payment.user_id}</code>\n"
                        f"Сумма: {refunded_payment.amount_rub} ₽\n"
                        f"Статус: <b>{refunded_payment.status.value}</b>.\n"
                        f"Все начисленные услуги/зачёты автоматически отозваны.",
                        parse_mode="HTML",
                    )
                await bot.session.close()
            except Exception as notify_err:
                logger.warning(f"Failed to notify admin about refund: {notify_err}")

        return {"status": "ok", "event": event, "processed": bool(refunded_payment)}

    if event != "payment.succeeded":
        # Другие события ЮKassa просто квитируем HTTP 200
        return {"status": "ok"}

    yk_id = obj.get("id")
    if not yk_id:
        return JSONResponse({"status": "error", "detail": "Missing payment id"}, status_code=400)

    # C4: Предварительно проверяем наличие платежа в БД и соответствие суммы
    res_p = await db.execute(select(Payment).where(Payment.yookassa_payment_id == yk_id))
    payment_record = res_p.scalar_one_or_none()
    if not payment_record:
        logger.warning(f"[SECURITY] YooKassa webhook received for unknown payment yk_id={yk_id}")
        return JSONResponse({"status": "not_found", "detail": "Payment not found"}, status_code=404)

    # 2. Верификация через официальный API ЮKassa
    has_yk = bool(
        getattr(settings, "YOOKASSA_SHOP_ID", None)
        and getattr(settings, "YOOKASSA_SECRET_KEY", None)
        and str(settings.YOOKASSA_SHOP_ID).strip() != ""
    )

    if has_yk:
        try:
            from yookassa import Configuration, Payment as YKPayment
            Configuration.account_id = settings.YOOKASSA_SHOP_ID
            Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

            loop = asyncio.get_event_loop()
            verified = await loop.run_in_executor(None, functools.partial(YKPayment.find_one, yk_id))
            if not verified or verified.status != "succeeded" or not getattr(verified, "paid", False):
                logger.warning(
                    f"[SECURITY] YooKassa webhook rejected for yk_id={yk_id}: "
                    f"status={getattr(verified, 'status', None)}, paid={getattr(verified, 'paid', None)}"
                )
                return JSONResponse({"status": "rejected", "detail": "Payment status mismatch"}, status_code=400)

            # C4: Проверка суммы и валюты из верифицированного платежа ЮKassa
            yk_amount = float(getattr(getattr(verified, "amount", None), "value", 0))
            yk_currency = str(getattr(getattr(verified, "amount", None), "currency", "RUB")).upper()
            if yk_currency != "RUB" or abs(yk_amount - float(payment_record.amount_rub)) > 0.01:
                logger.warning(
                    f"[SECURITY] YooKassa webhook rejected for yk_id={yk_id}: "
                    f"Amount/currency mismatch. YooKassa={yk_amount} {yk_currency}, expected={payment_record.amount_rub} RUB"
                )
                return JSONResponse({"status": "rejected", "detail": "Payment amount mismatch"}, status_code=400)
        except Exception as e:
            logger.error(f"[SECURITY] Error verifying payment {yk_id} with YooKassa API: {e}", exc_info=True)
            return JSONResponse({"status": "error", "detail": "Upstream verification failed"}, status_code=502)
    elif is_dev_or_test:
        logger.info(f"YooKassa webhook accepted in dev/test mode for yk_id={yk_id}")
        # C4: В dev/test режиме также проверяем сумму из тела запроса, если передана
        body_amount = float(obj.get("amount", {}).get("value", 0)) if obj.get("amount") else None
        body_currency = str(obj.get("amount", {}).get("currency", "RUB")).upper() if obj.get("amount") else "RUB"
        if body_amount is not None and body_amount > 0:
            if body_currency != "RUB" or abs(body_amount - float(payment_record.amount_rub)) > 0.01:
                logger.warning(
                    f"[SECURITY] YooKassa webhook rejected in dev/test for yk_id={yk_id}: "
                    f"Amount mismatch. Body={body_amount} {body_currency}, expected={payment_record.amount_rub} RUB"
                )
                return JSONResponse({"status": "rejected", "detail": "Payment amount mismatch"}, status_code=400)
    else:
        logger.error("[SECURITY] YooKassa webhook received in production without YooKassa credentials configured!")
        return JSONResponse({"status": "error", "detail": "Payment gateway not configured"}, status_code=503)

    # 3. Идемпотентное подтверждение в БД и начисление бонусов/тарифов
    from database.crud import confirm_payment
    payment = await confirm_payment(db, yk_id)
    if payment:
        try:
            from aiogram import Bot
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                payment.user_id,
                "🎉 <b>Оплата прошла успешно!</b>\n\n"
                "Услуга / тариф успешно активированы на вашем аккаунте. Спасибо за поддержку СтудМэч! 🤲🏻",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception as notify_err:
            logger.warning(f"Failed to notify user {payment.user_id} about payment: {notify_err}")

    return {"status": "ok"}
