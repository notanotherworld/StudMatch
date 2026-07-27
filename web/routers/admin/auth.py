"""
Авторизация модератора в веб-панели.
"""
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone

from web.dependencies import get_db, verify_password, create_token
from database.models import Admin

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login")
async def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Admin).where(Admin.login == login, Admin.is_active == True))
    admin = result.scalar_one_or_none()

    if not admin or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401,
        )

    # Обновляем last_login
    await db.execute(
        update(Admin).where(Admin.id == admin.id).values(last_login=datetime.now(timezone.utc))
    )
    await db.commit()

    token = create_token({"admin_id": admin.id, "role": admin.role.value})
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie("admin_token", token, httponly=True, samesite="lax", max_age=3600 * 8)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response
