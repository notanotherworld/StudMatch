"""
#1 Массовая рассылка в Telegram-бот.
Фильтры: все / верифицированные / режим карьера / режим знакомства.
Защиты: только superadmin (#4), CSRF (#2), XSS-экранирование (#1),
        валидация target, лимит длины текста.
"""
import html
import asyncio
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_

from web.dependencies import get_db, get_current_admin, check_csrf
from database.models import User, BroadcastLog

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

ALLOWED_TARGETS = {"all", "verified", "career", "dating"}
TARGET_LABELS = {
    "all":      "Всем пользователям",
    "verified": "Только верифицированным",
    "career":   "Режим «Карьера»",
    "dating":   "Режим «Знакомства»",
}
MAX_TEXT_LENGTH = 4096


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    from web.dependencies import generate_csrf_token
    csrf_token = generate_csrf_token(request.cookies.get("admin_token", ""))

    result = await db.execute(
        select(BroadcastLog).order_by(BroadcastLog.created_at.desc()).limit(20)
    )
    history = result.scalars().all()
    return templates.TemplateResponse(
        "admin/broadcast.html",
        {
            "request": request, "admin": admin, "history": history,
            "target_labels": TARGET_LABELS,
            "csrf_token": csrf_token,   # передаём токен в шаблон (#2)
        },
    )


@router.post("/broadcast/send", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def send_broadcast(
    request: Request,
    text: str = Form(...),
    target: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # Валидация target (#10 из аудита)
    if target not in ALLOWED_TARGETS:
        raise HTTPException(status_code=400, detail="Недопустимое значение target")

    # Лимит длины (#10 из аудита)
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Текст слишком длинный (макс. {MAX_TEXT_LENGTH} символов)")

    # XSS: экранируем HTML-теги из пользовательского ввода (#1)
    # Используем plain-text без parse_mode — безопаснее для рассылок
    safe_text = html.escape(text)

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
        text=safe_text,
        target=target,
        sent_count=0,
        failed_count=0,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    # Отправка через бот (без parse_mode — plain text, нет XSS) (#1)
    from bot.config import settings
    from aiogram import Bot
    bot = Bot(token=settings.BOT_TOKEN)

    sent = failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, safe_text)  # НЕТ parse_mode="HTML"
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Throttle: 20 msg/s

    await bot.session.close()

    # Обновляем счётчики
    await db.execute(
        update(BroadcastLog).where(BroadcastLog.id == log.id).values(
            sent_count=sent, failed_count=failed
        )
    )
    await db.commit()

    return RedirectResponse("/admin/broadcast", status_code=302)


@router.post("/broadcast/system-update", dependencies=[Depends(check_csrf)])
async def send_system_update(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручной запуск рассылки об обновлении платформы."""
    from bot.config import settings
    from aiogram import Bot
    from bot.services.update_broadcast import send_update_announcement

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        res = await send_update_announcement(bot)
    finally:
        await bot.session.close()

    # Записываем в лог рассылок
    log = BroadcastLog(
        text="🚀 Рассылка об обновлении платформы (Новые фичи)",
        target="all",
        sent_count=res.get("sent", 0),
        failed_count=res.get("failed", 0),
        admin_id=admin.id,
    )
    db.add(log)
    await db.commit()

    await log_admin_action(
        db, admin.id, "system_update_broadcast",
        f"Рассылка об обновлении: отправлено {res.get('sent', 0)}, ошибок {res.get('failed', 0)}"
    )

    return RedirectResponse("/admin/broadcast", status_code=302)


@router.post("/broadcast/weekly-yandex", dependencies=[Depends(check_csrf)])
async def send_weekly_yandex(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручной запуск рассылки Яндекс Топ-12."""
    from bot.config import settings
    from aiogram import Bot
    from bot.services.weekly_notifications import run_weekly_rank_notifications

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        await run_weekly_rank_notifications(bot)
    finally:
        await bot.session.close()

    return RedirectResponse("/admin/broadcast", status_code=302)


@router.post("/broadcast/weekly-challenge", dependencies=[Depends(check_csrf)])
async def send_weekly_challenge(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручной запуск рассылки Карьерный челлендж недели."""
    from bot.config import settings
    from aiogram import Bot
    from bot.services.weekly_notifications import run_weekly_challenge_notifications

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        await run_weekly_challenge_notifications(bot)
    finally:
        await bot.session.close()

    return RedirectResponse("/admin/broadcast", status_code=302)
