"""
#1 Центр управления рассылками в Telegram-бот.
- Точечный таргетинг: пол, режим, курс, вуз, стек навыков, рейтинг.
- Живой подсчет аудитории (AJAX).
- Запланированная отправка по таймеру.
- Медиа-баннеры и инлайн-кнопки.
"""
import os
import json
import html
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func

from web.dependencies import get_db, get_current_admin, check_csrf
from web.utils.audit import log_admin_action
from web.utils.uploads import save_avatar_upload
from database.models import User, Profile, University, BroadcastLog
from bot.services.scheduler import build_recipients_query, execute_broadcast_delivery

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

MAX_TEXT_LENGTH = 4096


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    from web.dependencies import generate_csrf_token
    csrf_token = generate_csrf_token(request.cookies.get("admin_token", ""))

    # Получаем вузы
    res_uni = await db.execute(select(University).order_by(University.name))
    universities = res_uni.scalars().all()

    # Получаем запланированные и завершенные рассылки
    result = await db.execute(
        select(BroadcastLog).order_by(BroadcastLog.created_at.desc()).limit(30)
    )
    history = result.scalars().all()

    # Общее количество активных студентов
    total_users_res = await db.execute(
        select(func.count(User.id)).where(User.is_active == True, User.is_fake == False, User.email_verified == True)
    )
    total_verified_users = total_users_res.scalar() or 0

    return templates.TemplateResponse(
        "admin/broadcast.html",
        {
            "request": request,
            "admin": admin,
            "universities": universities,
            "history": history,
            "total_users_count": total_verified_users,
            "csrf_token": csrf_token,
        },
    )


@router.post("/broadcast/count-recipients")
async def count_recipients_api(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """AJAX-эндпоинт для динамического подсчета подходящих получателей."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    query = build_recipients_query(data)
    # Считаем количество
    count_query = select(func.count()).select_from(query.subquery())
    res = await db.execute(count_query)
    count = res.scalar() or 0

    return JSONResponse({"count": count})


@router.post("/broadcast/send", dependencies=[Depends(check_csrf)])
async def send_broadcast_action(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    # Текст и медиа
    text: str = Form(...),
    photo: Optional[UploadFile] = File(None),
    button_text: Optional[str] = Form(None),
    button_url: Optional[str] = Form(None),
    # Таргетинг
    mode: str = Form("all"),
    gender: str = Form("all"),
    year: str = Form("all"),
    university_id: Optional[str] = Form(None),
    skills_query: Optional[str] = Form(None),
    min_rating: Optional[str] = Form(None),
    max_rating: Optional[str] = Form(None),
    verified_only: Optional[str] = Form("on"),
    # Таймер
    send_type: str = Form("now"),
    scheduled_datetime: Optional[str] = Form(None),
):
    """Создание и отправка / планирование точечной рассылки."""
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Текст слишком длинный (макс. {MAX_TEXT_LENGTH} символов)")

    # Сохраняем фото, если загружено
    photo_url = await save_avatar_upload(photo)

    # Упаковываем фильтры в JSON
    filters = {
        "mode": mode,
        "gender": gender,
        "year": year if year != "all" else None,
        "university_id": int(university_id) if (university_id and university_id.isdigit() and int(university_id) > 0) else None,
        "skills_query": skills_query.strip() if skills_query else "",
        "min_rating": float(min_rating) if (min_rating and min_rating.strip()) else None,
        "max_rating": float(max_rating) if (max_rating and max_rating.strip()) else None,
        "verified_only": (verified_only == "on" or verified_only == "true"),
    }
    filters_json = json.dumps(filters, ensure_ascii=False)

    # Определяем статус и время
    scheduled_at = None
    status = "completed"

    if send_type == "scheduled" and scheduled_datetime:
        try:
            # Парсим datetime (формат HTML5 datetime-local: YYYY-MM-DDTHH:MM)
            dt = datetime.fromisoformat(scheduled_datetime)
            if dt.tzinfo is None:
                # Считаем локальным и переводим в UTC
                dt = dt.replace(tzinfo=timezone.utc)
            scheduled_at = dt
            status = "pending"
        except Exception:
            status = "completed"

    # Создаем запись в BroadcastLog
    log = BroadcastLog(
        admin_id=admin.id,
        text=text.strip(),
        target=mode,
        target_filters=filters_json,
        photo_url=photo_url,
        button_text=button_text.strip() if button_text else None,
        button_url=button_url.strip() if button_url else None,
        scheduled_at=scheduled_at,
        status=status,
        sent_count=0,
        failed_count=0,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    if status == "pending":
        await log_admin_action(
            db, admin.id, "schedule_broadcast",
            f"Запланирована рассылка #{log.id} на {scheduled_at}"
        )
    else:
        # Отправляем прямо сейчас
        from bot.config import settings
        from aiogram import Bot
        bot = Bot(token=settings.BOT_TOKEN)
        try:
            await execute_broadcast_delivery(bot, log.id)
        finally:
            await bot.session.close()

        await log_admin_action(
            db, admin.id, "send_targeted_broadcast",
            f"Отправлена рассылка #{log.id}"
        )

    return RedirectResponse("/admin/broadcast", status_code=302)


@router.post("/broadcast/{broadcast_id}/cancel", dependencies=[Depends(check_csrf)])
async def cancel_scheduled_broadcast(
    broadcast_id: uuid.UUID,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Отмена запланированной рассылки."""
    res = await db.execute(
        select(BroadcastLog).where(BroadcastLog.id == broadcast_id, BroadcastLog.status == "pending")
    )
    blog = res.scalar_one_or_none()
    if blog:
        blog.status = "cancelled"
        await db.commit()
        await log_admin_action(
            db, admin.id, "cancel_broadcast", f"Отменена запланированная рассылка #{broadcast_id}"
        )

    return RedirectResponse("/admin/broadcast", status_code=302)


@router.post("/broadcast/{broadcast_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_broadcast_log(
    broadcast_id: uuid.UUID,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Удаление рассылки из истории."""
    await db.execute(delete(BroadcastLog).where(BroadcastLog.id == broadcast_id))
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

    log = BroadcastLog(
        text="🚀 Рассылка об обновлении платформы (Новые фичи)",
        target="all",
        sent_count=res.get("sent", 0),
        failed_count=res.get("failed", 0),
        admin_id=admin.id,
        status="completed",
    )
    db.add(log)
    await db.commit()

    await log_admin_action(
        db, admin.id, "system_update_broadcast",
        f"Рассылка об обновлении: отправлено {res.get('sent', 0)}, ошибок {res.get('failed', 0)}"
    )

    return RedirectResponse("/admin/broadcast", status_code=302)
