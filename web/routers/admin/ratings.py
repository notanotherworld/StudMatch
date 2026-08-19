"""Рейтинги: топ студентов, фильтры, экспорт CSV."""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import io, csv

from web.dependencies import get_db, get_current_admin
from database.models import Profile, User, University

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/ratings", response_class=HTMLResponse)
async def ratings_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    university_id: int = Query(default=0),
    major: str = Query(default=""),
    page: int = Query(default=1),
):
    per_page = 50
    offset = (page - 1) * per_page

    query = (
        select(Profile)
        .join(User, Profile.user_id == User.id)
        .options(selectinload(Profile.user))
        .where(Profile.is_complete == True, User.is_active == True)
    )
    if university_id:
        query = query.where(User.university_id == university_id)
    if major:
        query = query.where(Profile.major.ilike(f"%{major}%"))

    query = query.order_by(Profile.rating_score.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    profiles = result.scalars().all()

    unis = await db.execute(select(University).where(University.is_active == True))
    universities = unis.scalars().all()

    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/ratings.html",
        {
            "request": request,
            "admin": admin,
            "profiles": profiles,
            "universities": universities,
            "university_id": university_id,
            "major": major,
            "page": page,
            "csrf_token": token_str,
        },
    )


from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select, or_
from datetime import datetime

@router.get("/ratings/export.csv")
async def export_ratings_csv(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    university_id: int = Query(default=0),
    major: str = Query(default=""),
):
    """Экспорт рейтинга студентов в CSV с UTF-8 BOM и разделителем ';' для Excel."""
    query = (
        select(Profile)
        .join(User, Profile.user_id == User.id)
        .options(
            selectinload(Profile.user).selectinload(User.university),
            selectinload(Profile.user).selectinload(User.achievements),
        )
        .where(
            or_(Profile.is_complete == True, Profile.career_is_complete == True),
            User.is_active == True,
        )
    )

    if university_id:
        query = query.where(User.university_id == university_id)
    if major:
        query = query.where(Profile.major.ilike(f"%{major}%"))

    query = query.order_by(Profile.rating_score.desc())
    result = await db.execute(query)
    profiles = result.scalars().all()

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM для корректного отображения кириллицы в Excel
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Место в рейтинге",
        "Баллы рейтинга",
        "Имя / ФИО",
        "Telegram Username",
        "Email",
        "Почта подтверждена",
        "Университет",
        "Курс",
        "Специальность / Факультет",
        "Режим",
        "Подтверждённых достижений",
        "Банов за флуд",
        "Дата регистрации",
    ])

    for i, p in enumerate(profiles, 1):
        u = p.user
        uni = u.university.name if (u and u.university) else (p.major or "—")
        email_ver = "Да" if (u and u.email_verified) else "Нет"
        mode_str = "Карьера" if (u and u.mode and str(u.mode.value) == "career") else "Знакомства"
        verified_achievements = sum(1 for a in u.achievements if getattr(a.verified, 'value', a.verified) == "approved") if (u and u.achievements) else 0
        score_val = f"{p.rating_score:.0f}" if p.rating_score is not None else "0"

        writer.writerow([
            i,
            score_val,
            p.name or "Без имени",
            f"@{u.tg_username}" if (u and u.tg_username) else f"ID: {u.id if u else p.user_id}",
            u.email or "—" if u else "—",
            email_ver,
            uni,
            f"{p.year} курс" if p.year else "—",
            p.major or "—",
            mode_str,
            verified_achievements,
            u.flood_ban_count if u else 0,
            u.created_at.strftime("%Y-%m-%d %H:%M:%S") if (u and u.created_at) else "—",
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"studmatch_ratings_{now_str}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
