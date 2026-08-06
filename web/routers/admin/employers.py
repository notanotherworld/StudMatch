"""Управление работодателями и выдача доступа к анкетам."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
import uuid

from web.dependencies import get_db, get_current_admin, require_superadmin, hash_password, check_csrf
from database.models import Employer, EmployerProfileAccess, Profile, User

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/employers", response_class=HTMLResponse)
async def list_employers(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Employer).options(selectinload(Employer.profile_accesses)).order_by(Employer.created_at.desc())
    )
    employers = result.scalars().all()
    return templates.TemplateResponse(
        "admin/employers.html",
        {"request": request, "admin": admin, "employers": employers},
    )


@router.post("/employers/create", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def create_employer(
    company_name: str = Form(...),
    contact_name: str = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    admin=Depends(require_superadmin),  # только superadmin (#4)
    db: AsyncSession = Depends(get_db),
):
    employer = Employer(
        company_name=company_name,
        contact_name=contact_name,
        login=login,
        password_hash=hash_password(password),
        created_by=admin.id,
    )
    db.add(employer)
    await db.commit()
    return RedirectResponse("/admin/employers", status_code=302)


@router.get("/employers/{employer_id}", response_class=HTMLResponse)
async def employer_detail(
    employer_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    q: str = Query(default=""),
):
    result = await db.execute(
        select(Employer)
        .options(selectinload(Employer.profile_accesses))
        .where(Employer.id == employer_id)
    )
    employer = result.scalar_one_or_none()
    if not employer:
        return RedirectResponse("/admin/employers")

    # Поиск студентов для выдачи доступа
    search_profiles = []
    if q:
        search_result = await db.execute(
            select(Profile)
            .join(User, Profile.user_id == User.id)
            .where(Profile.name.ilike(f"%{q}%"), Profile.is_complete == True)
            .limit(10)
        )
        search_profiles = search_result.scalars().all()

    return templates.TemplateResponse(
        "admin/employer_detail.html",
        {
            "request": request, "admin": admin,
            "employer": employer, "q": q,
            "search_profiles": search_profiles,
        },
    )


@router.post("/employers/{employer_id}/grant", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def grant_access(
    employer_id: int,
    profile_id: str = Form(...),
    note: str = Form(default=""),
    admin=Depends(require_superadmin),  # только superadmin (#4)
    db: AsyncSession = Depends(get_db),
):
    profile_uuid = uuid.UUID(profile_id)
    access = EmployerProfileAccess(
        employer_id=employer_id,
        profile_id=profile_uuid,
        granted_by=admin.id,
        note=note,
    )
    db.add(access)
    await db.commit()
    return RedirectResponse(f"/admin/employers/{employer_id}", status_code=302)


@router.post("/employers/{employer_id}/toggle", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def toggle_employer(
    employer_id: int,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Employer).where(Employer.id == employer_id))
    employer = result.scalar_one_or_none()
    if employer:
        await db.execute(
            update(Employer).where(Employer.id == employer_id).values(is_active=not employer.is_active)
        )
        await db.commit()
    return RedirectResponse("/admin/employers", status_code=302)
