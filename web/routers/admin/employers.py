"""Управление работодателями, вакансиями и выдача доступа к анкетам."""
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
    company_description: str = Form(default=""),
    vacancies_description: str = Form(default=""),
    tg_contact: str = Form(default=""),
    website: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    employer = Employer(
        company_name=company_name.strip(),
        contact_name=contact_name.strip(),
        login=login.strip(),
        password_hash=hash_password(password),
        company_description=company_description.strip() or None,
        vacancies_description=vacancies_description.strip() or None,
        tg_contact=tg_contact.strip() or None,
        website=website.strip() or None,
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
    university_id: int = Query(default=0),
    year: int = Query(default=0),
):
    result = await db.execute(
        select(Employer)
        .options(
            selectinload(Employer.profile_accesses).selectinload(EmployerProfileAccess.profile).selectinload(Profile.user)
        )
        .where(Employer.id == employer_id)
    )
    employer = result.scalar_one_or_none()
    if not employer:
        return RedirectResponse("/admin/employers")

    # Получаем список вузов для фильтра
    unis_res = await db.execute(select(University).where(University.is_active == True).order_by(University.name))
    universities = unis_res.scalars().all()

    # Комплексный поиск студентов для выдачи доступа
    search_profiles = []
    clean_q = q.strip()
    clean_q_term = clean_q.lstrip("@")

    conditions = [
        or_(Profile.is_complete == True, Profile.career_is_complete == True),
        User.is_active == True,
    ]

    if clean_q_term:
        q_filters = [
            Profile.name.ilike(f"%{clean_q_term}%"),
            Profile.major.ilike(f"%{clean_q_term}%"),
            Profile.bio.ilike(f"%{clean_q_term}%"),
            Profile.career_bio.ilike(f"%{clean_q_term}%"),
            Profile.career_skills.ilike(f"%{clean_q_term}%"),
            User.tg_username.ilike(f"%{clean_q_term}%"),
            User.email.ilike(f"%{clean_q_term}%"),
        ]
        if clean_q_term.isdigit():
            q_filters.append(User.id == int(clean_q_term))
        conditions.append(or_(*q_filters))

    if university_id:
        conditions.append(User.university_id == university_id)
    if year:
        conditions.append(Profile.year == year)

    # Исключаем анкеты, к которым уже выдан доступ этому работодателю
    already_granted_profile_ids = [acc.profile_id for acc in employer.profile_accesses if acc.profile_id]
    if already_granted_profile_ids:
        conditions.append(~Profile.id.in_(already_granted_profile_ids))

    if clean_q or university_id or year:
        search_result = await db.execute(
            select(Profile)
            .options(
                selectinload(Profile.user).selectinload(User.university),
                selectinload(Profile.user).selectinload(User.achievements),
            )
            .join(User, Profile.user_id == User.id)
            .where(*conditions)
            .order_by(Profile.rating_score.desc())
            .limit(20)
        )
        search_profiles = search_result.scalars().all()

    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/employer_detail.html",
        {
            "request": request,
            "admin": admin,
            "employer": employer,
            "q": q,
            "university_id": university_id,
            "year": year,
            "universities": universities,
            "search_profiles": search_profiles,
            "csrf_token": token_str,
        },
    )


@router.post("/employers/{employer_id}/update", dependencies=[Depends(check_csrf)])
async def update_employer(
    employer_id: int,
    company_name: str = Form(...),
    contact_name: str = Form(...),
    company_description: str = Form(default=""),
    vacancies_description: str = Form(default=""),
    tg_contact: str = Form(default=""),
    website: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Employer)
        .where(Employer.id == employer_id)
        .values(
            company_name=company_name.strip(),
            contact_name=contact_name.strip(),
            company_description=company_description.strip() or None,
            vacancies_description=vacancies_description.strip() or None,
            tg_contact=tg_contact.strip() or None,
            website=website.strip() or None,
        )
    )
    await db.commit()
    return RedirectResponse(f"/admin/employers/{employer_id}", status_code=302)


@router.post("/employers/{employer_id}/grant", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def grant_access(
    employer_id: int,
    profile_id: str = Form(...),
    note: str = Form(default=""),
    admin=Depends(get_current_admin),
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

    # Уведомляем студента в Telegram с информацией о работодателе и открытых вакансиях
    prof_res = await db.execute(select(Profile).where(Profile.id == profile_uuid))
    student_prof = prof_res.scalar_one_or_none()
    emp_res = await db.execute(select(Employer).where(Employer.id == employer_id))
    emp = emp_res.scalar_one_or_none()

    if student_prof and emp:
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            msg = (
                f"👔 <b>Вашей анкетой заинтересовался работодатель!</b>\n\n"
                f"🏢 <b>Компания:</b> {emp.company_name}\n"
            )
            if emp.company_description:
                msg += f"📝 <b>О компании:</b> {emp.company_description}\n"
            if emp.vacancies_description:
                msg += f"💼 <b>Свободные вакансии:</b> {emp.vacancies_description}\n"
            if emp.tg_contact:
                contact = emp.tg_contact.strip().lstrip("@")
                msg += f"\n🔗 <b>Контакт для связи:</b> @{contact}"
            elif emp.website:
                msg += f"\n🌐 <b>Сайт компании:</b> {emp.website}"

            await bot.send_message(student_prof.user_id, msg, parse_mode="HTML")
            await bot.session.close()
        except Exception:
            pass

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
