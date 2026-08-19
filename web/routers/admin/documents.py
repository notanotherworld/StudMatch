"""Верификация документов модератором."""
from fastapi import APIRouter, Request, Depends, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_admin, require_superadmin, check_csrf
from bot.utils.minio_client import get_object_data
from database.models import Achievement, VerifiedStatus
from database.crud import approve_achievement, reject_achievement
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/documents", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = "pending",
):
    status_enum = VerifiedStatus(status) if status in ("pending", "approved", "rejected") else VerifiedStatus.pending

    result = await db.execute(
        select(Achievement)
        .options(selectinload(Achievement.user))
        .where(Achievement.verified == status_enum)
        .order_by(Achievement.created_at.desc())
    )
    achievements = result.scalars().all()

    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/documents.html",
        {
            "request": request,
            "admin": admin,
            "achievements": achievements,
            "current_status": status,
            "csrf_token": token_str,
        },
    )


@router.get("/documents/{achievement_id}/view")
async def view_document(
    achievement_id: str,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Прямая отдача/стриминг документа из MinIO в браузер модератора."""
    result = await db.execute(select(Achievement).where(Achievement.id == achievement_id))
    achievement = result.scalar_one_or_none()
    if not achievement or not achievement.document_url:
        return RedirectResponse("/admin/documents")

    try:
        file_bytes, content_type = get_object_data(achievement.document_url)
        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f"inline; filename=doc_{achievement_id}.{content_type.split('/')[-1]}",
            },
        )
    except Exception:
        return HTMLResponse("<h3>Файл документа не найден в хранилище</h3>", status_code=404)


@router.post("/documents/{achievement_id}/approve", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def approve_doc(
    achievement_id: str,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await approve_achievement(db, achievement_id, admin.id)

    # Уведомляем студента через бота
    result = await db.execute(select(Achievement).where(Achievement.id == achievement_id))
    ach = result.scalar_one_or_none()
    if ach:
        await log_admin_action(
            db=db,
            admin=admin,
            action="approve_document",
            target_type="achievement",
            target_id=str(achievement_id),
            details=f"Одобрен документ '{ach.title}' (+{ach.score:.0f} баллов) для студента #{ach.user_id}",
        )
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                ach.user_id,
                f"✅ <b>Достижение подтверждено!</b>\n\n"
                f"🏆 {ach.title}\n"
                f"💫 Начислено: +{ach.score:.0f} баллов к рейтингу",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse("/admin/documents?success=Достижение+подтверждено", status_code=302)


@router.post("/documents/{achievement_id}/reject", dependencies=[Depends(check_csrf)])
async def reject_doc(
    achievement_id: str,
    reason: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    clean_reason = reason.strip() or "Документ не соответствует требованиям"
    await reject_achievement(db, achievement_id, admin.id, clean_reason)

    result = await db.execute(select(Achievement).where(Achievement.id == achievement_id))
    ach = result.scalar_one_or_none()
    if ach:
        await log_admin_action(
            db=db,
            admin=admin,
            action="reject_document",
            target_type="achievement",
            target_id=str(achievement_id),
            details=f"Отклонен документ '{ach.title}' студента #{ach.user_id}. Причина: {clean_reason}",
        )
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                ach.user_id,
                f"❌ <b>Достижение отклонено</b>\n\n"
                f"🏷 {ach.title}\n"
                f"📋 Причина: {clean_reason}\n\n"
                f"Ты можешь загрузить исправленный документ.",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse("/admin/documents?success=Документ+отклонен", status_code=302)


# ─── #5: Пакетное одобрение ──────────────────────────────────────────────────
@router.post("/documents/approve-all", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def approve_all_by_user(
    user_id: int = Form(...),
    admin=Depends(require_superadmin),   # только superadmin (#4)
    db: AsyncSession = Depends(get_db),
):
    """Одобрить все pending-достижения конкретного пользователя."""
    result = await db.execute(
        select(Achievement).where(
            Achievement.user_id == user_id,
            Achievement.verified == VerifiedStatus.pending,
        )
    )
    achievements = result.scalars().all()

    for a in achievements:
        await approve_achievement(db, str(a.id), admin.id)

    if achievements:
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                user_id,
                f"✅ <b>Все ваши достижения подтверждены!</b>\n\n"
                f"Одобрено: {len(achievements)} достижений.\n"
                f"Рейтинг обновлён 🏆",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse("/admin/documents", status_code=302)


@router.post("/documents/approve-type", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def approve_by_type(
    ach_type: str = Form(...),
    admin=Depends(require_superadmin),   # только superadmin (#4)
    db: AsyncSession = Depends(get_db),
):
    """Одобрить все pending-достижения определённого типа."""
    from database.models import AchievementType
    try:
        type_enum = AchievementType(ach_type)
    except ValueError:
        return RedirectResponse("/admin/documents", status_code=302)

    result = await db.execute(
        select(Achievement).where(
            Achievement.type == type_enum,
            Achievement.verified == VerifiedStatus.pending,
        )
    )
    achievements = result.scalars().all()

    notified: set = set()
    for a in achievements:
        await approve_achievement(db, str(a.id), admin.id)
        notified.add(a.user_id)

    # Уведомляем каждого студента один раз
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        for uid in notified:
            try:
                await bot.send_message(
                    uid,
                    f"✅ <b>Достижение подтверждено!</b>\n\n"
                    f"Тип: {ach_type}\nРейтинг обновлён.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse("/admin/documents", status_code=302)


@router.post("/documents/batch-approve", dependencies=[Depends(check_csrf)])
async def batch_approve_docs(
    request: Request,
    doc_ids: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    ids = [i.strip() for i in doc_ids.split(",") if i.strip()]
    notified: set = set()
    for d_id in ids:
        await approve_achievement(db, d_id, admin.id)
        res = await db.execute(select(Achievement).where(Achievement.id == d_id))
        ach = res.scalar_one_or_none()
        if ach:
            notified.add(ach.user_id)

    if notified:
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            for uid in notified:
                try:
                    await bot.send_message(
                        uid,
                        "✅ <b>Ваши достижения подтверждены!</b>\n\nБаллы начислены в рейтинг 🏆",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse("/admin/documents", status_code=302)


@router.post("/documents/batch-reject", dependencies=[Depends(check_csrf)])
async def batch_reject_docs(
    request: Request,
    doc_ids: str = Form(...),
    reason: str = Form(default="Документ не соответствует требованиям"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    ids = [i.strip() for i in doc_ids.split(",") if i.strip()]
    notified: set = set()
    for d_id in ids:
        await reject_achievement(db, d_id, admin.id, reason)
        res = await db.execute(select(Achievement).where(Achievement.id == d_id))
        ach = res.scalar_one_or_none()
        if ach:
            notified.add(ach.user_id)

    if notified:
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            for uid in notified:
                try:
                    await bot.send_message(
                        uid,
                        f"❌ <b>Достижения отклонены</b>\n\n📋 Причина: {reason}",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse("/admin/documents", status_code=302)
