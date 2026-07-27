"""Управление пользователями: поиск, бан, сообщения."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_admin
from database.models import User, Profile

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
        {"request": request, "admin": admin, "users": users, "q": q, "page": page},
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
        {"request": request, "admin": admin, "user": user},
    )


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: int,
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


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(update(User).where(User.id == user_id).values(is_active=True))
    await db.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/verify-manual")
async def verify_user_manually(
    user_id: int,
    email: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ручная верификация студента модератором без отправки письма."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        values = {"email_verified": True}
        if email.strip():
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



@router.post("/users/{user_id}/message")
async def send_message_to_user(
    user_id: int,
    text: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Отправить произвольное сообщение студенту через бот."""
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(user_id, text, parse_mode="HTML")
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


# ─── #4: Ручное редактирование рейтинга ─────────────────────────────────────
@router.post("/users/{user_id}/rating")
async def adjust_rating(
    user_id: int,
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

        # Уведомляем студента
        try:
            from aiogram import Bot
            from bot.config import settings
            bot = Bot(token=settings.BOT_TOKEN)
            sign = "+" if delta >= 0 else ""
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
