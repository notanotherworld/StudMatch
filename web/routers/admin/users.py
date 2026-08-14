"""Управление пользователями: поиск, бан, сообщения."""
import html
import io
import csv
import re
from fastapi import APIRouter, Request, Depends, Form, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, or_
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_admin, check_csrf
from web.utils.audit import log_admin_action
from database.models import User, Profile, Swipe

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    q: str = Query(default=""),
    page: int = Query(default=1),
):
    per_page = 20
    offset = (page - 1) * per_page

    query = select(User).options(selectinload(User.profile), selectinload(User.university))

    if q:
        query = query.join(User.profile, isouter=True).where(
            or_(
                User.tg_username.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
                Profile.name.ilike(f"%{q}%"),
            )
        )

    query = query.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "admin": admin, "users": users, "q": q, "page": page,
         "csrf_token": getattr(request.state, "csrf_token", "")},
    )


@router.get("/users/export/csv")
async def export_users_csv(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт базы пользователей в CSV с UTF-8 BOM для Excel."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.profile), selectinload(User.university))
        .order_by(User.created_at.desc())
    )
    all_users = result.scalars().all()

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID Пользователя", "Username Telegram", "Email", "Почта подтверждена",
        "Имя в анкете", "Курс", "ВУЗ / Факультет", "Режим", "Суперлайки",
        "Рейтинг (баллы)", "Анкета заполнена", "Анкета видна", "Активен", "Дата регистрации",
    ])

    for u in all_users:
        prof = u.profile
        uni = u.university.name if u.university else (prof.major if prof else "")
        mode_name = "Карьера" if u.mode.value == "career" else "Знакомства"
        writer.writerow([
            u.id,
            f"@{u.tg_username}" if u.tg_username else "",
            u.email or "",
            "Да" if u.email_verified else "Нет",
            prof.name if prof else "",
            prof.year if prof else "",
            uni or "",
            mode_name,
            u.superlike_balance,
            f"{prof.rating_score:.0f}" if prof else "0",
            "Да" if prof and prof.is_complete else "Нет",
            "Да" if prof and prof.is_visible else "Нет",
            "Да" if u.is_active else "Заблокирован",
            u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=studmatch_users.csv"},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.profile), selectinload(User.achievements), selectinload(User.university))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse("/admin/users")

    return templates.TemplateResponse(
        "admin/user_detail.html",
        {"request": request, "admin": admin, "user": user,
         "csrf_token": getattr(request.state, "csrf_token", "")},
    )


@router.post("/users/{user_id}/ban", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def ban_user(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(User).where(User.id == user_id).values(is_active=False)
    )
    await db.execute(
        update(Profile).where(Profile.user_id == user_id).values(is_visible=False)
    )
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="user_ban", target_type="user", target_id=str(user_id),
        details="Пользователь заблокирован администратором", ip_address=client_ip
    )

    # Уведомляем пользователя
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(user_id, "🚫 Ваш аккаунт заблокирован модератором.")
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/unban", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def unban_user(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(update(User).where(User.id == user_id).values(is_active=True))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="user_unban", target_type="user", target_id=str(user_id),
        details="Пользователь разблокирован администратором", ip_address=client_ip
    )

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/verify-manual", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def verify_user_manually(
    user_id: int,
    email: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручная верификация студента модератором без отправки письма."""
    EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        values = {"email_verified": True}
        if email.strip():
            if not EMAIL_RE.match(email.strip()):
                return RedirectResponse(f"/admin/users/{user_id}", status_code=302)
            values["email"] = email.strip()

        await db.execute(
            update(User).where(User.id == user_id).values(**values)
        )
        await db.commit()

        # Уведомляем пользователя в Telegram
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                user_id,
                "✅ <b>Ваш аккаунт подтверждён модератором!</b>\n\n"
                "Вы успешно верифицированы. Теперь вам доступен выбор режима в боте (/start).",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/superlikes", dependencies=[Depends(check_csrf)])
async def adjust_superlikes(
    user_id: int,
    request: Request,
    delta: int = Form(...),
    reason: str = Form(default="Начисление администратором"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Начислить или списать суперлайки."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        new_balance = max(0, user.superlike_balance + delta)
        await db.execute(update(User).where(User.id == user_id).values(superlike_balance=new_balance))
        await db.commit()

        client_ip = request.client.host if request.client else None
        sign = "+" if delta >= 0 else ""
        await log_admin_action(
            db, admin, action="superlikes_adjust", target_type="user", target_id=str(user_id),
            details=f"Баланс суперлайков изменён на {sign}{delta} (Новый баланс: {new_balance}). Причина: {reason}",
            ip_address=client_ip,
        )

        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                user_id,
                f"⭐️ <b>Баланс суперлайков обновлён!</b>\n\n"
                f"Изменение: <b>{sign}{delta} ⭐️</b>\n"
                f"Текущий баланс: <b>{new_balance} ⭐️</b>\n"
                f"Причина: <i>{html.escape(reason)}</i>",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/reset-swipes", dependencies=[Depends(check_csrf)])
async def reset_user_swipes_admin(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сбросить исходящую историю свайпов пользователя."""
    await db.execute(delete(Swipe).where(Swipe.from_user_id == user_id))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="reset_swipes", target_type="user", target_id=str(user_id),
        details="История исходящих свайпов сброшена администратором",
        ip_address=client_ip,
    )

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/message", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def send_message_to_user(
    user_id: int,
    request: Request,
    text: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Отправить сообщение студенту через бот."""
    safe_text = html.escape(text.strip()[:4096])
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(user_id, f"💬 <b>Сообщение от администрации:</b>\n\n{safe_text}", parse_mode="HTML")
        await bot.session.close()

        client_ip = request.client.host if request.client else None
        await log_admin_action(
            db, admin, action="send_direct_message", target_type="user", target_id=str(user_id),
            details=f"Отправлено сообщение: {text[:150]}",
            ip_address=client_ip,
        )
    except Exception:
        pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/rating", dependencies=[Depends(check_csrf)])  # CSRF (#2)
async def adjust_rating(
    user_id: int,
    request: Request,
    delta: float = Form(...),
    reason: str = Form(default="Ручная корректировка"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Добавить или убрать баллы рейтинга вручную."""
    from database.models import Profile
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile:
        new_score = max(0.0, profile.rating_score + delta)
        await db.execute(
            update(Profile).where(Profile.user_id == user_id).values(rating_score=new_score)
        )
        await db.commit()

        client_ip = request.client.host if request.client else None
        sign = "+" if delta >= 0 else ""
        await log_admin_action(
            db, admin, action="rating_adjust", target_type="user", target_id=str(user_id),
            details=f"Рейтинг изменён на {sign}{delta:.0f} б. (Новый рейтинг: {new_score:.0f} б.). Причина: {reason}",
            ip_address=client_ip,
        )

        # Уведомляем студента
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                user_id,
                f"⭐ <b>Рейтинг обновлён модератором</b>\n\n"
                f"Изменение: <b>{sign}{delta:.0f} баллов</b>\n"
                f"Причина: {reason}\n"
                f"Новый рейтинг: <b>{new_score:.0f} б.</b>",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


# ─── #6: История свайпов пользователя ───────────────────────────────────────
@router.get("/users/{user_id}/swipes", response_class=HTMLResponse)
async def user_swipes(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    direction: str = Query(default="given"),  # given / received
):
    from database.models import Swipe, Profile
    from sqlalchemy.orm import selectinload

    if direction == "given":
        result = await db.execute(
            select(Swipe)
            .where(Swipe.from_user_id == user_id)
            .order_by(Swipe.created_at.desc())
            .limit(100)
        )
    else:
        result = await db.execute(
            select(Swipe)
            .where(Swipe.to_user_id == user_id)
            .order_by(Swipe.created_at.desc())
            .limit(100)
        )
    swipes = result.scalars().all()

    # Подгружаем профили для отображения имён
    ids = set()
    for s in swipes:
        ids.add(s.from_user_id)
        ids.add(s.to_user_id)

    profiles_result = await db.execute(
        select(Profile).where(Profile.user_id.in_(ids))
    )
    profiles_map = {p.user_id: p for p in profiles_result.scalars().all()}

    # Имя текущего пользователя
    user_result = await db.execute(select(User).where(User.id == user_id))
    target_user = user_result.scalar_one_or_none()

    return templates.TemplateResponse(
        "admin/swipe_history.html",
        {
            "request": request, "admin": admin,
            "target_user": target_user,
            "swipes": swipes, "profiles_map": profiles_map,
            "direction": direction, "user_id": user_id,
        },
    )
