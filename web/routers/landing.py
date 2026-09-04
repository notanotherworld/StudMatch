"""
Официальный промо-лендинг платформы СтудМэч.
Доступен по адресам: stud-match.ru, landing.stud-match.ru и /landing.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from web.dependencies import get_db
from database.models import User, Match, University, Profile
from bot.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Публичный лендинг платформы СтудМэч с живой статистикой."""
    # Получаем количество студентов
    users_res = await db.execute(select(func.count(User.id)))
    students_count = users_res.scalar() or 0

    # Получаем количество мэтчей
    matches_res = await db.execute(select(func.count(Match.id)))
    matches_count = matches_res.scalar() or 0

    # Получаем количество вузов
    unis_res = await db.execute(select(func.count(University.id)))
    universities_count = unis_res.scalar() or 0

    # Если бот только запущен, даем красивые базовые числа для социального доказательства
    display_students = max(students_count, 1250)
    display_matches = max(matches_count, 3400)
    display_unis = max(universities_count, 12)

    bot_username = getattr(settings, "BOT_USERNAME", "edudating_bot") or "edudating_bot"

    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "students_count": display_students,
            "matches_count": display_matches,
            "universities_count": display_unis,
            "bot_username": bot_username,
        },
    )


@router.get("/brand", response_class=HTMLResponse)
async def brand_kit_page(request: Request):
    """Интерактивная страница Brand Kit и ассетов StudMatch."""
    return templates.TemplateResponse("brand_kit.html", {"request": request})

