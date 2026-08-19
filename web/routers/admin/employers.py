"""Управление работодателями, вакансиями и выдача доступа к анкетам."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from sqlalchemy.orm import selectinload
from typing import Optional
import uuid

from web.dependencies import get_db, get_current_admin, require_superadmin, hash_password, check_csrf, generate_csrf_token
from database.models import Employer, EmployerProfileAccess, Profile, User, University
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/employers", response_class=HTMLResponse)
async def list_employers(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    error: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
):
    result = await db.execute(
        select(Employer).options(selectinload(Employer.profile_accesses)).order_by(Employer.created_at.desc())
    )
    employers = result.scalars().all()
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/employers.html",
        {
            "request": request,
            "admin": admin,
            "employers": employers,
            "csrf_token": token_str,
            "error_msg": error,
            "success_msg": success,
        },
    )


@router.post("/employers/create", dependencies=[Depends(check_csrf)])
async def create_employer(
    request: Request,
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
    from sqlalchemy import func, text
    clean_login = login.strip().lower()

    # Проверяем уникальность логина
    existing = await db.scalar(select(Employer).where(Employer.login == clean_login))
    if existing:
        return RedirectResponse("/admin/employers?error=Работодатель+с+таким+логином+уже+существует", status_code=302)

    try:
        max_id = await db.scalar(select(func.max(Employer.id))) or 0
        next_id = max_id + 1

        employer = Employer(
            id=next_id,
            company_name=company_name.strip(),
            contact_name=contact_name.strip(),
            login=clean_login,
            password_hash=hash_password(password),
            company_description=company_description.strip() or None,
            vacancies_description=vacancies_description.strip() or None,
            tg_contact=tg_contact.strip() or None,
            website=website.strip() or None,
            created_by=admin.id,
        )
        db.add(employer)
        await db.commit()
        await db.refresh(employer)

        try:
            await db.execute(text("SELECT setval('employers_id_seq', (SELECT MAX(id) FROM employers))"))
            await db.commit()
        except Exception:
            pass

        await log_admin_action(
            db=db,
            admin=admin,
            action="create_employer",
            target_type="employer",
            target_id=str(employer.id),
            details=f"Создан аккаунт работодателя #{employer.id} «{company_name.strip()}» (логин: {clean_login})",
        )
        return RedirectResponse("/admin/employers?success=Аккаунт+работодателя+успешно+создан", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/employers?error=Ошибка+создания:+{str(e)[:50]}", status_code=302)


@router.get("/employers/{employer_id}", response_class=HTMLResponse)
async def employer_detail(
    employer_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    q: str = Query(default=""),
    university_id: int = Query(default=0),
    year: int = Query(default=0),
    error: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
):
    result = await db.execute(
        select(Employer)
        .options(
            selectinload(Employer.profile_accesses)
            .selectinload(EmployerProfileAccess.profile)
            .selectinload(Profile.user)
            .selectinload(User.university)
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
            "error_msg": error,
            "success_msg": success,
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
    clean_company = company_name.strip()
    await db.execute(
        update(Employer)
        .where(Employer.id == employer_id)
        .values(
            company_name=clean_company,
            contact_name=contact_name.strip(),
            company_description=company_description.strip() or None,
            vacancies_description=vacancies_description.strip() or None,
            tg_contact=tg_contact.strip() or None,
            website=website.strip() or None,
        )
    )
    await db.commit()

    await log_admin_action(
        db=db,
        admin=admin,
        action="update_employer",
        target_type="employer",
        target_id=str(employer_id),
        details=f"Обновлены данные работодателя #{employer_id} «{clean_company}»",
    )

    return RedirectResponse(f"/admin/employers/{employer_id}?success=Данные+компании+обновлены", status_code=302)


@router.post("/employers/{employer_id}/grant", dependencies=[Depends(check_csrf)])
async def grant_access(
    employer_id: int,
    profile_id: str = Form(...),
    note: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        profile_uuid = uuid.UUID(str(profile_id).strip())
    except Exception:
        return RedirectResponse(f"/admin/employers/{employer_id}?error=Некорректный+идентификатор+анкеты", status_code=302)

    try:
        # Проверяем, существует ли уже доступ
        existing = await db.scalar(
            select(EmployerProfileAccess).where(
                EmployerProfileAccess.employer_id == employer_id,
                EmployerProfileAccess.profile_id == profile_uuid,
            )
        )
        if existing:
            if note.strip():
                existing.note = note.strip()
                await db.commit()
            return RedirectResponse(f"/admin/employers/{employer_id}?success=Доступ+к+анкете+уже+был+выдан+ранее", status_code=302)

        access = EmployerProfileAccess(
            id=uuid.uuid4(),
            employer_id=employer_id,
            profile_id=profile_uuid,
            granted_by=admin.id,
            note=note.strip() or None,
        )
        db.add(access)
        await db.commit()

        prof_res = await db.execute(select(Profile).where(Profile.id == profile_uuid))
        student_prof = prof_res.scalar_one_or_none()
        emp_res = await db.execute(select(Employer).where(Employer.id == employer_id))
        emp = emp_res.scalar_one_or_none()

        student_name = student_prof.name if student_prof else str(profile_uuid)
        emp_name = emp.company_name if emp else str(employer_id)

        await log_admin_action(
            db=db,
            admin=admin,
            action="grant_employer_profile_access",
            target_type="employer",
            target_id=str(employer_id),
            details=f"Выдан доступ к анкете студента {student_name} работодателю «{emp_name}» (заметка: {note})",
        )

        # Уведомляем студента в Telegram с информацией о работодателе и открытых вакансиях
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

        return RedirectResponse(f"/admin/employers/{employer_id}?success=Кандидат+успешно+выдан+работодателю", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/employers/{employer_id}?error=Ошибка+выдачи:+{str(e)[:50]}", status_code=302)


@router.post("/employers/{employer_id}/toggle", dependencies=[Depends(check_csrf)])
async def toggle_employer(
    employer_id: int,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Employer).where(Employer.id == employer_id))
    employer = result.scalar_one_or_none()
    if employer:
        new_status = not employer.is_active
        await db.execute(
            update(Employer).where(Employer.id == employer_id).values(is_active=new_status)
        )
        await db.commit()

        await log_admin_action(
            db=db,
            admin=admin,
            action="toggle_employer",
            target_type="employer",
            target_id=str(employer_id),
            details=f"Изменён статус активности работодателя #{employer_id} «{employer.company_name}» -> {'Активен' if new_status else 'Отключён'}",
        )
    return RedirectResponse("/admin/employers", status_code=302)
