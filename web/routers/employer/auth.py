"""Авторизация работодателя/HR."""
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from web.dependencies import get_db, verify_password, create_token
from database.models import Employer

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("employer/login.html", {"request": request, "error": None})


@router.post("/login")
async def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Employer).where(Employer.login == login, Employer.is_active == True)
    )
    employer = result.scalar_one_or_none()

    if not employer or not verify_password(password, employer.password_hash):
        return templates.TemplateResponse(
            "employer/login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401,
        )

    token = create_token({"employer_id": employer.id})
    response = RedirectResponse(url="/employer/profiles", status_code=302)
    response.set_cookie("employer_token", token, httponly=True, samesite="lax", max_age=3600 * 8)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/employer/login", status_code=302)
    response.delete_cookie("employer_token")
    return response
