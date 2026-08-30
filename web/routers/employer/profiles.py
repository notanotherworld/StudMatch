"""Кабинет HR: просмотр выданных анкет студентов и управление статусами кандидатов."""
from typing import Optional
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_employer
from database.models import EmployerProfileAccess, Profile, Achievement, VerifiedStatus, User
from database.crud import get_employer_profiles, get_employer_profile_counts, update_employer_candidate_status

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


import csv
import io
from fastapi.responses import HTMLResponse, RedirectResponse, Response

@router.get("/profiles", response_class=HTMLResponse)
async def profiles_list(
    request: Request,
    tab: str = Query(default="all"),
    q: Optional[str] = Query(default=None),
    year: Optional[str] = Query(default=None),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Список выданных HR анкет с фильтрацией по вкладкам, поиском по ключевым словам и курсу."""
    # Безопасный парсинг года (курса)
    year_int: Optional[int] = None
    if year is not None and str(year).strip().isdigit():
        year_int = int(str(year).strip())

    filter_status = tab if tab in ("suitable", "archived") else None
    accesses = await get_employer_profiles(db, employer.id, status=filter_status)
    counts = await get_employer_profile_counts(db, employer.id)

    # Фильтрация по поисковому запросу и курсу
    filtered_accesses = []
    for acc in accesses:
        prof = acc.profile
        if not prof:
            continue
        if year_int is not None and prof.year != year_int:
            continue
        if q and q.strip():
            query_lower = q.strip().lower()
            name_match = prof.name and query_lower in prof.name.lower()
            major_match = prof.major and query_lower in prof.major.lower()
            skills_match = prof.career_custom_skills and query_lower in prof.career_custom_skills.lower()
            goal_match = prof.career_goal and query_lower in prof.career_goal.lower()
            if not (name_match or major_match or skills_match or goal_match):
                continue
        filtered_accesses.append(acc)

    return templates.TemplateResponse(
        "employer/profiles.html",
        {
            "request": request,
            "employer": employer,
            "accesses": filtered_accesses,
            "current_tab": tab,
            "counts": counts,
            "q": q or "",
            "year": year_int if year_int is not None else "",
        },
    )


@router.get("/profiles/export/csv")
async def export_profiles_csv(
    tab: str = Query(default="all"),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт списка кандидатов (Все / Подходящие) в CSV для HR."""
    filter_status = tab if tab in ("suitable", "archived") else None
    accesses = await get_employer_profiles(db, employer.id, status=filter_status)

    output = io.StringIO()
    # Write UTF-8 BOM so Excel opens Cyrillic properly
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Имя", "ВУЗ", "Курс", "Специальность", "Рейтинг (баллы)", 
        "Навыки и стек", "Формат работы", "Портфолио", "Telegram", "Статус в HR", "Заметка HR", "Дата выдачи"
    ])

    for acc in accesses:
        prof = acc.profile
        user = prof.user if prof else None
        if not prof:
            continue

        status_label = "Подходящий" if acc.status == "suitable" else ("В архиве" if acc.status == "archived" else "Активный")
        tg = f"@{user.tg_username}" if user and user.tg_username else "Скрыт"
        univ = user.university.short_name if user and user.university else "РУДН"
        granted_str = acc.granted_at.strftime("%d.%m.%Y") if acc.granted_at else ""

        writer.writerow([
            prof.name or "—",
            univ,
            f"{prof.year} курс" if prof.year else "—",
            prof.major or "—",
            int(prof.rating_score or 0),
            prof.career_custom_skills or "—",
            prof.career_work_format or "Любой",
            prof.career_portfolio_url or "—",
            tg,
            status_label,
            acc.hr_comment or acc.note or "",
            granted_str,
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    filename = f"candidates_{employer.company_name}_{tab}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/profiles/{access_id}", response_class=HTMLResponse)
async def profile_detail(
    access_id: str,
    request: Request,
    saved: Optional[str] = Query(default=None),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Детальный просмотр анкеты студента с гарантированной отметкой о просмотре."""
    try:
        access_uuid = uuid.UUID(access_id)
    except ValueError:
        return RedirectResponse("/employer/profiles")

    result = await db.execute(
        select(EmployerProfileAccess)
        .options(
            selectinload(EmployerProfileAccess.profile)
            .selectinload(Profile.user)
            .selectinload(User.university),
        )
        .where(
            EmployerProfileAccess.id == access_uuid,
            EmployerProfileAccess.employer_id == employer.id,
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        return RedirectResponse("/employer/profiles")

    # Гарантированно отмечаем просмотр в БД и в текущем объекте
    if not access.viewed_at:
        access.viewed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(access)

    profile = access.profile
    user = profile.user if profile else None

    # Только подтверждённые достижения (без документов!)
    achievements = []
    if user:
        result2 = await db.execute(
            select(Achievement).where(
                Achievement.user_id == user.id,
                Achievement.verified == VerifiedStatus.approved,
            )
        )
        achievements = result2.scalars().all()

    return templates.TemplateResponse(
        "employer/profile_detail.html",
        {
            "request": request,
            "employer": employer,
            "access": access,
            "profile": profile,
            "user": user,
            "achievements": achievements,
            "saved": bool(saved),
        },
    )


@router.post("/profiles/{access_id}/status")
async def set_candidate_status(
    access_id: str,
    request: Request,
    status: str = Form(...),
    next_url: Optional[str] = Form(default=None),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Смена статуса кандидата (active / suitable / archived)."""
    try:
        access_uuid = uuid.UUID(access_id)
    except ValueError:
        return RedirectResponse("/employer/profiles")

    if status in ("suitable", "archived", "active"):
        await update_employer_candidate_status(db, access_uuid, employer.id, new_status=status)

    if next_url and next_url.startswith("/employer"):
        return RedirectResponse(next_url, status_code=302)
    return RedirectResponse(f"/employer/profiles/{access_id}", status_code=302)


@router.post("/profiles/{access_id}/comment")
async def update_candidate_comment(
    access_id: str,
    request: Request,
    hr_comment: str = Form(default=""),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Сохранение личной заметки HR по кандидату."""
    try:
        access_uuid = uuid.UUID(access_id)
    except ValueError:
        return RedirectResponse("/employer/profiles")

    await update_employer_candidate_status(
        db, access_uuid, employer.id, new_status=None, hr_comment=hr_comment.strip()
    )
    return RedirectResponse(f"/employer/profiles/{access_id}?saved=1", status_code=302)
