"""
Настройки компании и профиля HR:
Редактирование контактных данных, описания компании и смена пароля.
"""
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from web.dependencies import get_db, get_current_employer, verify_password, hash_password
from database.models import Employer

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    success: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Страница настроек работодателя."""
    return templates.TemplateResponse(
        "employer/settings.html",
        {
            "request": request,
            "employer": employer,
            "success": success,
            "error": error,
        },
    )


@router.post("/settings/profile")
async def update_profile(
    request: Request,
    contact_name: str = Form(...),
    tg_contact: str = Form(default=""),
    website: str = Form(default=""),
    company_description: str = Form(default=""),
    vacancies_description: str = Form(default=""),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Обновление контактной информации компании."""
    await db.execute(
        update(Employer)
        .where(Employer.id == employer.id)
        .values(
            contact_name=contact_name.strip(),
            tg_contact=tg_contact.strip() if tg_contact else None,
            website=website.strip() if website else None,
            company_description=company_description.strip() if company_description else None,
            vacancies_description=vacancies_description.strip() if vacancies_description else None,
        )
    )
    await db.commit()
    return RedirectResponse("/employer/settings?success=Профиль+успешно+обновлен", status_code=302)


@router.post("/settings/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Смена пароля от кабинета работодателя."""
    if not verify_password(current_password, employer.password_hash):
        return RedirectResponse("/employer/settings?error=Текущий+пароль+введен+неверно", status_code=302)

    if len(new_password) < 6:
        return RedirectResponse("/employer/settings?error=Новый+пароль+должен+быть+не+менее+6+символов", status_code=302)

    if new_password != confirm_password:
        return RedirectResponse("/employer/settings?error=Новые+пароли+не+совпадают", status_code=302)

    new_hash = hash_password(new_password)
    await db.execute(
        update(Employer)
        .where(Employer.id == employer.id)
        .values(password_hash=new_hash)
    )
    await db.commit()
    return RedirectResponse("/employer/settings?success=Пароль+успешно+изменен", status_code=302)
