"""
Заявки работодателя на подбор кандидатов / студентов.
Создание заявок, отслеживание статусов, отправка уведомлений модераторам.
"""
from typing import Optional
import html
import uuid

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from web.dependencies import get_db, get_current_employer
from database.models import EmployerRequest, Employer, Admin
from bot.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/requests", response_class=HTMLResponse)
async def requests_page(
    request: Request,
    success: Optional[int] = Query(default=0),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Страница подачи заявок на подбор студентов и история заявок."""
    req_res = await db.execute(
        select(EmployerRequest)
        .where(EmployerRequest.employer_id == employer.id)
        .order_by(EmployerRequest.created_at.desc())
    )
    requests_list = list(req_res.scalars().all())

    return templates.TemplateResponse(
        "employer/requests.html",
        {
            "request": request,
            "employer": employer,
            "requests_list": requests_list,
            "success": bool(success),
        },
    )


@router.post("/requests")
async def create_request(
    request: Request,
    title: str = Form(...),
    direction: str = Form(default="IT / Разработка"),
    skills_required: str = Form(default=""),
    work_format: str = Form(default="Любой"),
    candidates_count: int = Form(default=5),
    comment: str = Form(default=""),
    employer=Depends(get_current_employer),
    db: AsyncSession = Depends(get_db),
):
    """Создание новой заявки на подбор студентов работодателем."""
    req_obj = EmployerRequest(
        employer_id=employer.id,
        title=title.strip(),
        direction=direction.strip(),
        skills_required=skills_required.strip() if skills_required else None,
        work_format=work_format.strip(),
        candidates_count=max(1, min(candidates_count, 100)),
        comment=comment.strip() if comment else None,
        status="pending",
    )
    db.add(req_obj)
    await db.commit()

    # Отправляем уведомление администраторам/модераторам в Telegram (если настроен бот)
    try:
        from aiogram import Bot
        from aiogram.enums import ParseMode
        bot = Bot(token=settings.BOT_TOKEN)
        
        # Получаем админов с tg_chat_id
        admin_res = await db.execute(select(Admin).where(Admin.tg_chat_id.isnot(None), Admin.is_active == True))
        admins = admin_res.scalars().all()

        msg_text = (
            f"💼 <b>Новая заявка на подбор студентов!</b>\n\n"
            f"🏢 <b>Компания:</b> {html.escape(employer.company_name)}\n"
            f"👤 <b>Контакт:</b> {html.escape(employer.contact_name)} ({html.escape(employer.tg_contact or '—')})\n"
            f"🎯 <b>Позиция:</b> {html.escape(title)}\n"
            f"📚 <b>Направление:</b> {html.escape(direction)}\n"
            f"💼 <b>Формат:</b> {html.escape(work_format)}\n"
            f"👥 <b>Нужно кандидатов:</b> {candidates_count}\n"
        )
        if skills_required:
            msg_text += f"🛠 <b>Стек / Навыки:</b> {html.escape(skills_required)}\n"
        if comment:
            msg_text += f"💬 <b>Комментарий:</b> {html.escape(comment)}\n"

        msg_text += "\n👉 <i>Откройте панель управления СтудМэч для выдачи анкет.</i>"

        for adm in admins:
            if adm.tg_chat_id:
                try:
                    await bot.send_message(adm.tg_chat_id, msg_text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse("/employer/requests?success=1", status_code=302)
