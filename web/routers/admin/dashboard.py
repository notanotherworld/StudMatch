"""Dashboard: аналитика для модератора + графики (Chart.js)."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone, timedelta
import json

from web.dependencies import get_db, get_current_admin
from database.models import User, Profile, Swipe, Match, Payment, Achievement, PaymentStatus, VerifiedStatus

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Статистика пользователей
    total_users = await db.scalar(select(func.count()).select_from(User))
    verified_users = await db.scalar(select(func.count()).select_from(User).where(User.email_verified == True))
    new_today = await db.scalar(select(func.count()).select_from(User).where(User.created_at >= today))
    new_week = await db.scalar(select(func.count()).select_from(User).where(User.created_at >= week_ago))

    # Свайпы и мэтчи
    total_swipes = await db.scalar(select(func.count()).select_from(Swipe))
    total_matches = await db.scalar(select(func.count()).select_from(Match))
    matches_week = await db.scalar(select(func.count()).select_from(Match).where(Match.created_at >= week_ago))

    # Достижения на проверке
    pending_docs = await db.scalar(
        select(func.count()).select_from(Achievement).where(Achievement.verified == VerifiedStatus.pending)
    )

    # Монетизация
    revenue_total = await db.scalar(
        select(func.sum(Payment.amount_rub)).where(Payment.status == PaymentStatus.succeeded)
    ) or 0
    revenue_month = await db.scalar(
        select(func.sum(Payment.amount_rub)).where(
            and_(Payment.status == PaymentStatus.succeeded, Payment.created_at >= month_ago)
        )
    ) or 0

    stats = {
        "total_users": total_users or 0,
        "verified_users": verified_users or 0,
        "new_today": new_today or 0,
        "new_week": new_week or 0,
        "total_swipes": total_swipes or 0,
        "total_matches": total_matches or 0,
        "matches_week": matches_week or 0,
        "pending_docs": pending_docs or 0,
        "revenue_total": float(revenue_total),
        "revenue_month": float(revenue_month),
    }

    # ── #2: Данные для графиков (30 дней) ──────────────────────────
    reg_result = await db.execute(
        select(
            func.date_trunc("day", User.created_at).label("day"),
            func.count(User.id).label("cnt"),
        )
        .where(User.created_at >= month_ago)
        .group_by("day").order_by("day")
    )
    reg_chart = [
        {"day": r[0].strftime("%d.%m"), "count": r[1]}
        for r in reg_result.all()
    ]

    matches_chart_result = await db.execute(
        select(
            func.date_trunc("day", Match.created_at).label("day"),
            func.count(Match.id).label("cnt"),
        )
        .where(Match.created_at >= month_ago)
        .group_by("day").order_by("day")
    )
    matches_chart = [
        {"day": r[0].strftime("%d.%m"), "count": r[1]}
        for r in matches_chart_result.all()
    ]

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request, "admin": admin, "stats": stats,
            "reg_chart_json": json.dumps(reg_chart, ensure_ascii=False),
            "matches_chart_json": json.dumps(matches_chart, ensure_ascii=False),
        },
    )
