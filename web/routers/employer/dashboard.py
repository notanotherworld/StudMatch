"""
Главный Дашборд работодателя / HR-портал.
Метрики подбора, воронка найма, последние кандидаты и заявки.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_employer
from database.models import EmployerProfileAccess, Profile, User, EmployerRequest, University
from database.crud import get_employer_profile_counts

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def employer_dashboard(
    request: Request,
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Главный дашборд HR: метрики, воронка, последние анкеты и активные заявки."""
    # Метрики по кандидатам
    counts = await get_employer_profile_counts(db, employer.id)

    # Количество просмотренных
    viewed_res = await db.execute(
        select(func.count(EmployerProfileAccess.id)).where(
            EmployerProfileAccess.employer_id == employer.id,
            EmployerProfileAccess.viewed_at.isnot(None),
        )
    )
    viewed_count = viewed_res.scalar() or 0
    total_count = counts.get("all", 0)
    viewed_pct = int((viewed_count / total_count * 100)) if total_count > 0 else 0
    suitable_pct = int((counts.get("suitable", 0) / total_count * 100)) if total_count > 0 else 0

    # Средний рейтинг кандидатов
    avg_score_res = await db.execute(
        select(func.avg(Profile.rating_score))
        .select_from(EmployerProfileAccess)
        .join(Profile, EmployerProfileAccess.profile_id == Profile.id)
        .where(EmployerProfileAccess.employer_id == employer.id)
    )
    avg_score = avg_score_res.scalar() or 0.0

    # Последние выданные анкеты
    recent_accesses_res = await db.execute(
        select(EmployerProfileAccess)
        .options(
            selectinload(EmployerProfileAccess.profile)
            .selectinload(Profile.user)
            .selectinload(User.university)
        )
        .where(EmployerProfileAccess.employer_id == employer.id)
        .order_by(EmployerProfileAccess.granted_at.desc())
        .limit(6)
    )
    recent_accesses = list(recent_accesses_res.scalars().all())

    # Последние заявки компании на подбор
    recent_requests_res = await db.execute(
        select(EmployerRequest)
        .where(EmployerRequest.employer_id == employer.id)
        .order_by(EmployerRequest.created_at.desc())
        .limit(4)
    )
    recent_requests = list(recent_requests_res.scalars().all())

    return templates.TemplateResponse(
        "employer/dashboard.html",
        {
            "request": request,
            "employer": employer,
            "counts": counts,
            "viewed_count": viewed_count,
            "viewed_pct": viewed_pct,
            "suitable_pct": suitable_pct,
            "avg_score": round(avg_score, 1),
            "recent_accesses": recent_accesses,
            "recent_requests": recent_requests,
        },
    )
