"""
Маршрут веб-админки для диагностики и тестирования всех сервисов платформы.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from web.dependencies import get_db, get_current_admin, generate_csrf_token, check_csrf
from bot.config import settings
from bot.services.health_checker import run_full_diagnostics

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/health", response_class=HTMLResponse)
async def health_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Страница визуальной диагностики всех сервисов платформы."""
    csrf_token = generate_csrf_token(request.cookies.get("admin_token", ""))

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        diag = await run_full_diagnostics(bot, db=db)
    finally:
        await bot.session.close()

    return templates.TemplateResponse(
        "admin/health.html",
        {
            "request": request,
            "admin": admin,
            "csrf_token": csrf_token,
            "diag": diag,
        },
    )


@router.post("/health/run", dependencies=[Depends(check_csrf)])
async def run_health_api(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """API точка для повторного мгновенного запуска диагностики через AJAX."""
    bot = Bot(token=settings.BOT_TOKEN)
    try:
        diag = await run_full_diagnostics(bot, db=db)
    finally:
        await bot.session.close()

    return JSONResponse(diag)
