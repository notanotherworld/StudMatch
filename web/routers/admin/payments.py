"""
#7 Детализация монетизации: транзакции, фильтры, статистика по продуктам.
#10 Экспорт персональных данных: очередь запросов + отправка студенту.
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone, timedelta
import io, csv, json

from web.dependencies import get_db, get_current_admin
from database.models import Payment, PaymentStatus, PaymentProduct, User, DataExportRequest, ExportStatus

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


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

    # Статистика по продуктам (только succeeded)
    stats_result = await db.execute(
        select(Payment.product, func.count(Payment.id), func.sum(Payment.amount_rub))
        .where(Payment.status == PaymentStatus.succeeded)
        .group_by(Payment.product)
    )
    product_stats = [
        {"product": row[0].value, "count": row[1], "revenue": float(row[2] or 0)}
        for row in stats_result.all()
    ]

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

    return templates.TemplateResponse(
        "admin/payments.html",
        {
            "request": request, "admin": admin,
            "payments": payments, "product_stats": product_stats,
            "daily_revenue": daily_revenue,
            "current_product": product, "current_status": status,
            "page": page, "export_requests": export_requests,
        },
    )


@router.get("/payments/export.csv")
async def export_payments_csv(
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
@router.post("/payments/export-data/{request_id}/send")
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
