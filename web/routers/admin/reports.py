"""
#8 Система жалоб: просмотр, решение (бан / снятие жалобы).
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from web.dependencies import get_db, get_current_admin, check_csrf
from database.models import Report, ReportStatus, User, Profile

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = Query(default="pending"),
):
    status_enum = ReportStatus(status) if status in ("pending", "resolved", "dismissed") else ReportStatus.pending

    result = await db.execute(
        select(Report)
        .options(
            selectinload(Report.reporter),
            selectinload(Report.reported),
        )
        .where(Report.status == status_enum)
        .order_by(Report.created_at.desc())
    )
    reports = result.scalars().all()

    # Считаем кол-во жалоб на каждого пользователя (для индикатора опасности)
    from sqlalchemy import func
    count_result = await db.execute(
        select(Report.reported_id, func.count(Report.id).label("cnt"))
        .where(Report.status == ReportStatus.pending)
        .group_by(Report.reported_id)
    )
    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/reports.html",
        {
            "request": request,
            "admin": admin,
            "reports": reports,
            "current_status": status,
            "report_counts": report_counts,
            "csrf_token": token_str,
        },
    )


@router.post("/reports/{report_id}/ban", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def resolve_ban(
    report_id: str,
    note: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Одобрить жалобу + забанить нарушителя."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        return RedirectResponse("/admin/reports", status_code=302)

    now = datetime.now(timezone.utc)
    await db.execute(
        update(Report).where(Report.id == report_id).values(
            status=ReportStatus.resolved, resolved_by=admin.id,
            resolution_note=note or "Забанен по жалобе",
            resolved_at=now,
        )
    )
    await db.execute(
        update(User).where(User.id == report.reported_id).values(is_active=False)
    )
    await db.execute(
        update(Profile).where(Profile.user_id == report.reported_id).values(is_visible=False)
    )
    await db.commit()

    # Уведомляем нарушителя
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(
            report.reported_id,
            "🚫 <b>Ваш аккаунт заблокирован</b> по жалобе пользователей.\n"
            "Если вы считаете это ошибкой — обратитесь в поддержку.",
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse("/admin/reports", status_code=302)


@router.post("/reports/{report_id}/dismiss", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def dismiss_report(
    report_id: str,
    note: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Отклонить жалобу — нарушений не найдено."""
    await db.execute(
        update(Report).where(Report.id == report_id).values(
            status=ReportStatus.dismissed, resolved_by=admin.id,
            resolution_note=note or "Нарушений не найдено",
            resolved_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return RedirectResponse("/admin/reports", status_code=302)
