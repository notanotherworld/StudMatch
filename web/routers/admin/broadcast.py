"""
#1 Массовая рассылка в Telegram-бот.
Фильтры: все / верифицированные / режим карьера / режим знакомства.
"""
import asyncio
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from web.dependencies import get_db, get_current_admin
from database.models import User, BroadcastLog

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

TARGET_LABELS = {
    "all":      "Всем пользователям",
    "verified": "Только верифицированным",
    "career":   "Режим «Карьера»",
    "dating":   "Режим «Знакомства»",
}


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BroadcastLog).order_by(BroadcastLog.created_at.desc()).limit(20)
    )
    history = result.scalars().all()
    return templates.TemplateResponse(
        "admin/broadcast.html",
        {"request": request, "admin": admin, "history": history,
         "target_labels": TARGET_LABELS},
    )


@router.post("/broadcast/send")
async def send_broadcast(
    request: Request,
    text: str = Form(...),
    target: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # Собираем получателей
    query = select(User.id).where(User.is_active == True)
    if target == "verified":
        query = query.where(User.email_verified == True)
    elif target == "career":
        query = query.where(and_(User.email_verified == True, User.mode == "career"))
    elif target == "dating":
        query = query.where(and_(User.email_verified == True, User.mode == "dating"))

    result = await db.execute(query)
    user_ids = [row[0] for row in result.all()]

    # Логируем рассылку
    log = BroadcastLog(
        admin_id=admin.id,
        text=text,
        target=target,
        sent_count=0,
        failed_count=0,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    # Отправка через бот (в фоне)
    from bot.config import settings
    from aiogram import Bot
    bot = Bot(token=settings.BOT_TOKEN)

    sent = failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # Throttle: 20 msg/s

    await bot.session.close()

    # Обновляем счётчики
    from sqlalchemy import update
    from database.models import BroadcastLog as BL
    async with db:
        await db.execute(
            update(BL).where(BL.id == log.id).values(sent_count=sent, failed_count=failed)
        )
        await db.commit()

    return RedirectResponse("/admin/broadcast", status_code=302)
