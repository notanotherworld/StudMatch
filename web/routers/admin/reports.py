"""
#8 Система жалоб: просмотр, решение (бан / снятие жалобы).
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import uuid

from web.dependencies import get_db, get_current_admin, check_csrf, generate_csrf_token
from database.models import Report, ReportStatus, User, Profile
from web.utils.audit import log_admin_action

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
            selectinload(Report.reporter).selectinload(User.profile),
            selectinload(Report.reported).selectinload(User.profile),
        )
        .where(Report.status == status_enum)
        .order_by(Report.created_at.desc())
    )
    reports = result.scalars().all()

    # Считаем кол-во жалоб на каждого пользователя (для индикатора опасности)
    count_result = await db.execute(
        select(Report.reported_id, func.count(Report.id).label("cnt"))
        .where(Report.status == ReportStatus.pending)
        .group_by(Report.reported_id)
    )
    report_counts = {row[0]: row[1] for row in count_result.all()}

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


@router.post("/reports/{report_id}/ban", dependencies=[Depends(check_csrf)])
async def resolve_ban(
    report_id: str,
    request: Request,
    note: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Одобрить жалобу + забанить нарушителя."""
    try:
        report_uuid = uuid.UUID(report_id) if isinstance(report_id, str) else report_id
    except Exception:
        return RedirectResponse("/admin/reports?error=Некорректный+ID+жалобы", status_code=302)

    result = await db.execute(select(Report).where(Report.id == report_uuid))
    report = result.scalar_one_or_none()
    if not report:
        return RedirectResponse("/admin/reports?error=Жалоба+не+найдена", status_code=302)

    now = datetime.now(timezone.utc)
    resolution_text = note.strip() or "Забанен по жалобе пользователей"

    await db.execute(
        update(Report).where(Report.id == report_uuid).values(
            status=ReportStatus.resolved,
            resolved_by=admin.id,
            resolution_note=resolution_text,
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

    await log_admin_action(
        db=db,
        admin=admin,
        action="ban_user_by_report",
        target_type="user",
        target_id=str(report.reported_id),
        details=f"Бан по жалобе #{report_id}: {resolution_text}",
    )

    # Уведомляем нарушителя в боте
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(
            report.reported_id,
            f"🚫 <b>Ваш аккаунт заблокирован</b> модератором.\n\n"
            f"Причина: <i>{resolution_text}</i>\n\n"
            "Если вы считаете это ошибкой — обратитесь в поддержку.",
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse("/admin/reports?status=pending", status_code=302)


@router.post("/reports/{report_id}/dismiss", dependencies=[Depends(check_csrf)])
async def dismiss_report(
    report_id: str,
    request: Request,
    note: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Отклонить жалобу — нарушений не найдено."""
    try:
        report_uuid = uuid.UUID(report_id) if isinstance(report_id, str) else report_id
    except Exception:
        return RedirectResponse("/admin/reports?error=Некорректный+ID+жалобы", status_code=302)

    result = await db.execute(select(Report).where(Report.id == report_uuid))
    report = result.scalar_one_or_none()
    if not report:
        return RedirectResponse("/admin/reports?error=Жалоба+не+найдена", status_code=302)

    dismiss_text = note.strip() or "Нарушений не обнаружено"
    await db.execute(
        update(Report).where(Report.id == report_uuid).values(
            status=ReportStatus.dismissed,
            resolved_by=admin.id,
            resolution_note=dismiss_text,
            resolved_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    await log_admin_action(
        db=db,
        admin=admin,
        action="dismiss_report",
        target_type="report",
        target_id=str(report_id),
        details=f"Отклонена жалоба на пользователя #{report.reported_id}: {dismiss_text}",
    )

    return RedirectResponse("/admin/reports?status=pending", status_code=302)
