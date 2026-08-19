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


@router.get("/ratings/export.csv")
async def export_ratings_csv(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile)
        .join(User, Profile.user_id == User.id)
        .options(selectinload(Profile.user))
        .where(Profile.is_complete == True, User.is_active == True)
        .order_by(Profile.rating_score.desc())
        .limit(500)
    )
    profiles = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#", "Имя", "Курс", "Направление", "Email", "Рейтинг", "Режим"])
    for i, p in enumerate(profiles, 1):
        writer.writerow([
            i, p.name, p.year, p.major,
            p.user.email, p.rating_score, p.user.mode.value
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ratings.csv"},
    )
