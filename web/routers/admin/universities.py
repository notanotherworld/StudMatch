"""Управление университетами."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import Optional

from web.dependencies import get_db, get_current_admin, check_csrf, generate_csrf_token
from database.models import University
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/universities", response_class=HTMLResponse)
async def list_universities(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    error: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
):
    result = await db.execute(select(University).order_by(University.id))
    universities = result.scalars().all()

    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/universities.html",
        {
            "request": request,
            "admin": admin,
            "universities": universities,
            "csrf_token": token_str,
            "error_msg": error,
            "success_msg": success,
        },
    )


@router.post("/universities/create", dependencies=[Depends(check_csrf)])
async def create_university(
    request: Request,
    name: str = Form(...),
    short_name: str = Form(...),
    email_domains: str = Form(...),
    city: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    clean_name = name.strip()
    clean_short_name = short_name.strip()
    clean_email_domains = email_domains.strip()
    clean_city = city.strip()

    if not clean_name or not clean_short_name or not clean_email_domains:
        return RedirectResponse("/admin/universities?error=Заполните+все+обязательные+поля", status_code=302)

    try:
        uni = University(
            name=clean_name,
            short_name=clean_short_name,
            email_domains=clean_email_domains,
            city=clean_city or "Москва",
        )
        db.add(uni)
        await db.commit()
        await db.refresh(uni)

        await log_admin_action(
            admin_id=admin.id,
            action="create_university",
            details=f"Создан вуз #{uni.id} «{clean_name}» ({clean_short_name})",
            db=db,
        )
        return RedirectResponse("/admin/universities?success=Университет+успешно+добавлен", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/universities?error=Ошибка+создания:+{str(e)[:50]}", status_code=302)


@router.post("/universities/{uni_id}/toggle", dependencies=[Depends(check_csrf)])
async def toggle_university(
    uni_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(select(University).where(University.id == uni_id))
        uni = result.scalar_one_or_none()
        if uni:
            uni.is_active = not uni.is_active
            await db.commit()

            status_str = "активирован" if uni.is_active else "деактивирован"
            await log_admin_action(
                admin_id=admin.id,
                action="toggle_university",
                details=f"Вуз #{uni_id} ({uni.short_name}) {status_str}",
                db=db,
            )
            return RedirectResponse("/admin/universities?success=Статус+вуза+изменен", status_code=302)
        return RedirectResponse("/admin/universities?error=Вуз+не+найден", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/universities?error=Ошибка+изменения+статуса:+{str(e)[:50]}", status_code=302)
