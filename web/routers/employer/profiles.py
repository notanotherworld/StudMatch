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
    view: str = Query(default="table"),
    q: Optional[str] = Query(default=None),
    year: Optional[str] = Query(default=None),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Список выданных HR анкет с переключением Таблица/Канбан, фильтрацией и поиском."""
    year_int: Optional[int] = None
    if year is not None and str(year).strip().isdigit():
        year_int = int(str(year).strip())

    filter_status = tab if tab in ("suitable", "archived", "new", "screening", "interview", "offer", "hired", "rejected") else None
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

    # Для канбан-доски группируем кандидатов по колонкам
    kanban_groups = {
        "new": [],
        "screening": [],
        "interview": [],
        "offer": [],
        "hired": [],
        "archived": [],
    }
    # Для канбана берем все анкеты работодателя (с учетом фильтров)
    for acc in filtered_accesses:
        st = acc.status or "new"
        if st in ("active", None):
            st = "new"
        elif st == "suitable":
            st = "interview"
        elif st == "rejected":
            st = "archived"

        if st in kanban_groups:
            kanban_groups[st].append(acc)
        else:
            kanban_groups["new"].append(acc)

    return templates.TemplateResponse(
        "employer/profiles.html",
        {
            "request": request,
            "employer": employer,
            "accesses": filtered_accesses,
            "kanban_groups": kanban_groups,
            "current_tab": tab,
            "current_view": view,
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
    """Экспорт списка кандидатов в CSV для HR."""
    filter_status = tab if tab in ("suitable", "archived", "new", "screening", "interview", "offer", "hired") else None
    accesses = await get_employer_profiles(db, employer.id, status=filter_status)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Имя", "ВУЗ", "Курс", "Специальность", "Рейтинг (баллы)", 
        "Оценка HR (1-5)", "Навыки и стек", "Формат работы", "Портфолио", "Telegram", "Этап воронки", "Заметка HR", "Дата выдачи"
    ])

    for acc in accesses:
        prof = acc.profile
        user = prof.user if prof else None
        if not prof:
            continue

        stage_names = {
            "new": "Новый",
            "screening": "Скрининг",
            "interview": "Собеседование",
            "offer": "Оффер",
            "hired": "Нанят",
            "suitable": "Шортлист",
            "archived": "В архиве",
            "rejected": "Отказ",
        }
        status_label = stage_names.get(acc.status, "Новый")
        tg = f"@{user.tg_username}" if user and user.tg_username else "Скрыт"
        univ = user.university.short_name if user and user.university else "РУДН"
        granted_str = acc.granted_at.strftime("%d.%m.%Y") if acc.granted_at else ""

        writer.writerow([
            prof.name or "—",
            univ,
            f"{prof.year} курс" if prof.year else "—",
            prof.major or "—",
            int(prof.rating_score or 0),
            acc.hr_rating or 0,
            prof.career_custom_skills or "—",
            prof.career_work_format or "Любой",
            prof.career_portfolio_url or "—",
            tg,
            status_label,
            acc.hr_comment or acc.note or "",
            granted_str,
        ])

    import urllib.parse
    raw_filename = f"candidates_{employer.company_name}_{tab}.csv"
    encoded_filename = urllib.parse.quote(raw_filename)
    ascii_filename = f"candidates_{tab}.csv"

    csv_data = output.getvalue().encode("utf-8")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
        },
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

    # Гарантированно отмечаем просмотр в БД
    if not access.viewed_at:
        access.viewed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(access)

    profile = access.profile
    user = profile.user if profile else None

    # Подтверждённые достижения студента
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


@router.get("/profiles/{access_id}/json")
async def profile_detail_json(
    access_id: str,
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """JSON данные кандидата для Quick View Drawer."""
    try:
        access_uuid = uuid.UUID(access_id)
    except ValueError:
        return {"error": "Invalid ID"}

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
    if not access or not access.profile:
        return {"error": "Not found"}

    prof = access.profile
    user = prof.user

    # Отмечаем просмотр
    if not access.viewed_at:
        access.viewed_at = datetime.now(timezone.utc)
        await db.commit()

    # Достижения
    achievements = []
    if user:
        res2 = await db.execute(
            select(Achievement).where(
                Achievement.user_id == user.id,
                Achievement.verified == VerifiedStatus.approved,
            )
        )
        for a in res2.scalars().all():
            achievements.append({
                "title": a.title,
                "type": a.type.value,
                "score": int(a.score or 0),
            })

    # Расчёт Match Score % на основе рейтинга (от 70% до 99%)
    base_match = min(99, max(72, int(70 + (prof.rating_score or 0) / 15)))

    return {
        "success": True,
        "id": str(access.id),
        "name": prof.name or "Студент",
        "university": user.university.short_name if user and user.university else "РУДН",
        "university_full": user.university.name if user and user.university else "Российский университет дружбы народов",
        "year": prof.year or 1,
        "major": prof.major or "Специальность не указана",
        "rating_score": int(prof.rating_score or 0),
        "match_score": base_match,
        "status": access.status or "new",
        "hr_rating": access.hr_rating or 0,
        "hr_recommendation": access.hr_recommendation or "neutral",
        "hr_tags": access.hr_tags or "",
        "hr_comment": access.hr_comment or "",
        "skills": [s.strip() for s in (prof.career_custom_skills or "").split(",") if s.strip()],
        "goal": prof.career_goal or prof.goal or "Цели не указаны",
        "work_format": prof.career_work_format or "Любой формат",
        "portfolio_url": prof.career_portfolio_url or "",
        "tg_username": user.tg_username if user and user.tg_username else None,
        "email": user.email if user else None,
        "email_verified": user.email_verified if user else False,
        "is_premium": user.is_premium if user else False,
        "granted_at": access.granted_at.strftime("%d.%m.%Y") if access.granted_at else "",
        "note": access.note or "",
        "achievements": achievements,
    }


@router.post("/profiles/{access_id}/status")
async def set_candidate_status(
    access_id: str,
    request: Request,
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Смена статуса и скоринга кандидата (поддержка Form и JSON)."""
    try:
        access_uuid = uuid.UUID(access_id)
    except ValueError:
        return RedirectResponse("/employer/profiles")

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            status = body.get("status")
            hr_rating = body.get("hr_rating")
            hr_recommendation = body.get("hr_recommendation")
            hr_tags = body.get("hr_tags")
            hr_comment = body.get("hr_comment")
            
            await update_employer_candidate_status(
                db, access_uuid, employer.id,
                new_status=status,
                hr_rating=hr_rating,
                hr_recommendation=hr_recommendation,
                hr_tags=hr_tags,
                hr_comment=hr_comment,
            )
            return {"success": True, "status": status}
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        form = await request.form()
        status = form.get("status")
        next_url = form.get("next_url")
        valid_statuses = ("new", "screening", "interview", "offer", "hired", "archived", "rejected", "suitable", "active")
        if status in valid_statuses:
            await update_employer_candidate_status(db, access_uuid, employer.id, new_status=status)

        if next_url and next_url.startswith("/employer"):
            return RedirectResponse(next_url, status_code=302)
        return RedirectResponse(f"/employer/profiles/{access_id}", status_code=302)


@router.post("/profiles/{access_id}/comment")
async def update_candidate_comment(
    access_id: str,
    request: Request,
    hr_comment: str = Form(default=""),
    hr_rating: Optional[int] = Form(default=None),
    hr_recommendation: Optional[str] = Form(default=None),
    hr_tags: Optional[str] = Form(default=None),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Сохранение личной заметки и оценки HR по кандидату."""
    try:
        access_uuid = uuid.UUID(access_id)
    except ValueError:
        return RedirectResponse("/employer/profiles")

    await update_employer_candidate_status(
        db, access_uuid, employer.id,
        hr_comment=hr_comment.strip(),
        hr_rating=hr_rating,
        hr_recommendation=hr_recommendation,
        hr_tags=hr_tags,
    )
    return RedirectResponse(f"/employer/profiles/{access_id}?saved=1", status_code=302)


