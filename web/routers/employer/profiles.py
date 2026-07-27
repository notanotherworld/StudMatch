"""Кабинет HR: просмотр выданных анкет студентов."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_employer
from database.models import EmployerProfileAccess, Profile, Achievement, VerifiedStatus
from database.crud import mark_profile_viewed, get_employer_profiles

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/profiles", response_class=HTMLResponse)
async def profiles_list(
    request: Request,
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Список выданных HR анкет."""
    accesses = await get_employer_profiles(db, employer.id)

    return templates.TemplateResponse(
        "employer/profiles.html",
        {
            "request": request,
            "employer": employer,
            "accesses": accesses,
        },
    )


@router.get("/profiles/{access_id}", response_class=HTMLResponse)
async def profile_detail(
    access_id: str,
    request: Request,
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Детальный просмотр анкеты студента."""
    import uuid
    access_uuid = uuid.UUID(access_id)

    result = await db.execute(
        select(EmployerProfileAccess)
        .options(
            selectinload(EmployerProfileAccess.profile).selectinload(Profile.user),
        )
        .where(
            EmployerProfileAccess.id == access_uuid,
            EmployerProfileAccess.employer_id == employer.id,
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        return RedirectResponse("/employer/profiles")

    # Отмечаем просмотр
    if not access.viewed_at:
        await mark_profile_viewed(db, access_uuid)

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
        },
    )
