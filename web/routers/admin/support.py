"""
Служба поддержки и обратной связи (Support Deck):
Просмотр обращений пользователей, детальная диагностика устройств, смена статусов и ответы через бота.
"""
from fastapi import APIRouter, Request, Depends, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import uuid
import json
import html
import logging

from web.dependencies import get_db, get_current_admin, check_csrf, generate_csrf_token
from database.models import SupportTicket, TicketStatus, User, Profile, University
from web.utils.audit import log_admin_action
from bot.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/support", response_class=HTMLResponse)
async def support_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = Query(default="open"),
    category: str = Query(default="all"),
    q: str = Query(default=""),
):
    query = (
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.user).selectinload(User.profile),
            selectinload(SupportTicket.user).selectinload(User.university),
        )
        .order_by(SupportTicket.created_at.desc())
    )

    if status != "all":
        try:
            status_enum = TicketStatus(status)
            query = query.where(SupportTicket.status == status_enum)
        except ValueError:
            pass

    if category != "all" and category:
        query = query.where(SupportTicket.category == category)

    if q.strip():
        search = f"%{q.strip()}%"
        if q.strip().isdigit():
            user_id_val = int(q.strip())
            query = query.where(or_(SupportTicket.user_id == user_id_val, SupportTicket.message.ilike(search)))
        else:
            query = query.join(SupportTicket.user).outerjoin(User.profile).where(
                or_(
                    SupportTicket.message.ilike(search),
                    User.tg_username.ilike(search),
                    Profile.name.ilike(search),
                )
            )

    result = await db.execute(query)
    tickets = result.scalars().all()

    # Считаем количество тикетов по статусам
    count_res = await db.execute(
        select(SupportTicket.status, func.count(SupportTicket.id))
        .group_by(SupportTicket.status)
    )
    status_counts = {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in count_res.all()}
    total_tickets = sum(status_counts.values())

    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    # Парсим JSON телеметрии для каждого тикета
    ticket_items = []
    for t in tickets:
        device_parsed = None
        if t.device_info:
            try:
                device_parsed = json.loads(t.device_info)
            except Exception:
                device_parsed = {"raw": t.device_info}

        ticket_items.append({
            "ticket": t,
            "device": device_parsed,
        })

    return templates.TemplateResponse(
        "admin/support.html",
        {
            "request": request,
            "admin": admin,
            "ticket_items": ticket_items,
            "current_status": status,
            "current_category": category,
            "search_query": q,
            "status_counts": status_counts,
            "total_tickets": total_tickets,
            "csrf_token": token_str,
        },
    )


@router.post("/support/{ticket_id}/reply", dependencies=[Depends(check_csrf)])
async def reply_support_ticket(
    ticket_id: str,
    reply: str = Form(...),
    status: str = Form("resolved"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        t_uuid = uuid.UUID(ticket_id)
    except Exception:
        return RedirectResponse("/admin/support?error=Некорректный+ID+обращения", status_code=302)

    ticket = await db.get(SupportTicket, t_uuid)
    if not ticket:
        return RedirectResponse("/admin/support?error=Обращение+не+найдено", status_code=302)

    clean_reply = reply.strip()
    ticket.admin_reply = clean_reply
    if status in ("open", "in_progress", "resolved", "closed"):
        ticket.status = TicketStatus(status)
    if ticket.status in (TicketStatus.resolved, TicketStatus.closed):
        ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolved_by = admin.id
    ticket.updated_at = datetime.now(timezone.utc)

    await db.commit()

    # Отправляем сообщение студенту через Telegram Bot
    if clean_reply:
        try:
            from aiogram import Bot
            bot = Bot(token=settings.BOT_TOKEN)
            try:
                cat_names = {
                    "bug": "🐛 Ошибка / Баг",
                    "feature": "💡 Идея / Предложение",
                    "question": "❓ Вопрос по работе",
                    "account": "👤 Профиль / ВУЗ",
                    "other": "💬 Другое обращение",
                }
                cat_title = cat_names.get(ticket.category, ticket.category)
                status_labels = {
                    "open": "🟡 Открыто",
                    "in_progress": "🔵 В работе",
                    "resolved": "🟢 Решено",
                    "closed": "⚫ Закрыто",
                }
                st_text = status_labels.get(ticket.status.value, ticket.status.value)
                msg_text = (
                    f"💬 <b>Ответ службы заботы StudMatch</b>\n\n"
                    f"<i>По вашему обращению #{str(ticket.id)[:8]} ({cat_title}):</i>\n\n"
                    f"{html.escape(clean_reply)}\n\n"
                    f"Статус обращения: <b>{st_text}</b>"
                )
                await bot.send_message(ticket.user_id, msg_text, parse_mode="HTML")
            finally:
                await bot.session.close()
        except Exception as e:
            logger.warning(f"Failed to send ticket reply to user {ticket.user_id}: {e}")

    await log_admin_action(
        db,
        admin,
        "support_reply",
        target_type="support_ticket",
        target_id=str(ticket.id),
        details=f"Status: {ticket.status.value}. Reply: {clean_reply[:120]}",
    )

    return RedirectResponse(f"/admin/support?status={status}&success=Ответ+успешно+отправлен", status_code=302)


@router.post("/support/{ticket_id}/status", dependencies=[Depends(check_csrf)])
async def update_ticket_status(
    ticket_id: str,
    status: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        t_uuid = uuid.UUID(ticket_id)
    except Exception:
        return RedirectResponse("/admin/support?error=Некорректный+ID+обращения", status_code=302)

    ticket = await db.get(SupportTicket, t_uuid)
    if not ticket:
        return RedirectResponse("/admin/support?error=Обращение+не+найдено", status_code=302)

    if status in ("open", "in_progress", "resolved", "closed"):
        ticket.status = TicketStatus(status)
        if ticket.status in (TicketStatus.resolved, TicketStatus.closed):
            ticket.resolved_at = datetime.now(timezone.utc)
        ticket.resolved_by = admin.id
        ticket.updated_at = datetime.now(timezone.utc)
        await db.commit()

        await log_admin_action(
            db,
            admin,
            "support_status_change",
            target_type="support_ticket",
            target_id=str(ticket.id),
            details=f"Changed status to {ticket.status.value}",
        )

    return RedirectResponse(f"/admin/support?status={status}", status_code=302)
