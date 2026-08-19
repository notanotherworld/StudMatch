"""
Журнал согласий на обработку персональных данных (152-ФЗ РФ).
Просмотр, поиск, фильтры и экспорт юридического отчёта в CSV (Excel).
"""
import io
import csv
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Depends, Query, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_admin
from database.models import User, Profile, University

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/consents", response_class=HTMLResponse)
async def consents_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = Query(default="all"),
    q: str = Query(default=""),
    page: int = Query(default=1),
):
    per_page = 30
    offset = (page - 1) * per_page

    query = select(User).options(
        selectinload(User.profile),
        selectinload(User.university),
    )

    # Фильтр по статусу
    if status == "accepted":
        query = query.where(User.consent_given == True)
    elif status == "pending":
        query = query.where(User.consent_given == False)

    # Поиск по имени, никнейму, ID или email
    if q.strip():
        search_term = f"%{q.strip()}%"
        query = query.outerjoin(Profile, User.id == Profile.user_id).where(
            or_(
                User.tg_username.ilike(search_term),
                User.email.ilike(search_term),
                Profile.name.ilike(search_term),
                func.cast(User.id, String if False else func.text).ilike(search_term) if False else User.tg_username.ilike(search_term),
            )
        )

    # Подсчет общих метрик
    total_users = await db.scalar(select(func.count(User.id))) or 0
    accepted_count = await db.scalar(select(func.count(User.id)).where(User.consent_given == True)) or 0
    pending_count = total_users - accepted_count

    # Получение списка пользователей
    query = query.order_by(User.consent_at.desc().nullslast(), User.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/consents.html",
        {
            "request": request,
            "admin": admin,
            "users": users,
            "total_users": total_users,
            "accepted_count": accepted_count,
            "pending_count": pending_count,
            "current_status": status,
            "q": q,
            "page": page,
            "csrf_token": token_str,
        },
    )


@router.get("/consents/export/csv")
async def export_consents_csv(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = Query(default="all"),
):
    """Экспорт реестра согласий 152-ФЗ в CSV с UTF-8 BOM."""
    query = select(User).options(
        selectinload(User.profile),
        selectinload(User.university),
    )
    if status == "accepted":
        query = query.where(User.consent_given == True)
    elif status == "pending":
        query = query.where(User.consent_given == False)

    query = query.order_by(User.consent_at.desc().nullslast(), User.created_at.desc())
    result = await db.execute(query)
    all_users = result.scalars().all()

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Telegram ID", "Username", "ФИО / Имя в анкете", "Email",
        "Вуз", "Статус согласия ОПД", "Дата и время фиксации согласия (UTC)",
        "Версия соглашения", "Правовое основание",
    ])

    for u in all_users:
        prof_name = u.profile.name if u.profile and u.profile.name else "—"
        uni_name = u.university.short_name if u.university else "—"
        consent_status = "Принято (Да)" if u.consent_given else "Не принято / Ожидает"
        consent_date = u.consent_at.strftime("%Y-%m-%d %H:%M:%S") if u.consent_at else "—"
        
        writer.writerow([
            u.id,
            f"@{u.tg_username}" if u.tg_username else "—",
            prof_name,
            u.email or "—",
            uni_name,
            consent_status,
            consent_date,
            "Версия 1.0",
            "152-ФЗ РФ «О персональных данных»",
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=studmatch_consents_152fz.csv"},
    )
