"""Управление пользователями: поиск, бан, сообщения."""
import html
import io
import csv
import re
from typing import Optional, List, Dict, Any, Set
from fastapi import APIRouter, Request, Depends, Form, Query, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, or_, and_, func, exists
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_admin, check_csrf
from web.utils.audit import log_admin_action
from database.models import User, Profile, Swipe, Match, SwipeAction, ModeEnum, Report

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    q: str = Query(default=""),
    is_fake: Optional[str] = Query(default=None),
    filter_type: Optional[str] = Query(default=None),
    page: int = Query(default=1),
):
    try:
        from sqlalchemy import func
        per_page = 20
        offset = max(0, (page - 1) * per_page)

        active_banned_ids = set()
        try:
            from bot.middlewares.throttling import get_redis
            r = get_redis()
            keys = await r.keys("temp_ban:*")
            for k in keys:
                uid_str = k.split(":")[-1]
                if uid_str.isdigit():
                    active_banned_ids.add(int(uid_str))
            lvl_keys = await r.keys("flood_ban_level:*")
            for k in lvl_keys:
                uid_str = k.split(":")[-1]
                if uid_str.isdigit():
                    active_banned_ids.add(int(uid_str))
        except Exception:
            pass

        query = select(User).options(selectinload(User.profile), selectinload(User.university))

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        if filter_type == "spammers":
            spammer_conditions = [User.flood_ban_count > 0, User.is_flagged_spammer == True]
            if active_banned_ids:
                spammer_conditions.append(User.id.in_(list(active_banned_ids)))
            query = query.where(or_(*spammer_conditions))
            query = query.order_by(User.flood_ban_count.desc(), User.last_banned_at.desc().nullslast())
        elif filter_type == "premium":
            query = query.where(User.premium_until > now)
            query = query.order_by(User.premium_until.desc().nullslast())
        elif filter_type == "verified":
            query = query.where(User.email_verified == True)
            query = query.order_by(User.created_at.desc().nullslast())
        elif filter_type == "unverified":
            query = query.where(or_(User.email_verified == False, User.email_verified.is_(None)))
            query = query.order_by(User.created_at.desc().nullslast())
        else:
            if is_fake == "true":
                query = query.where(User.is_fake == True)
            elif is_fake == "false":
                query = query.where(or_(User.is_fake == False, User.is_fake.is_(None)))
            query = query.order_by(User.created_at.desc().nullslast())

        if q:
            query = query.join(User.profile, isouter=True).where(
                or_(
                    User.tg_username.ilike(f"%{q}%"),
                    User.email.ilike(f"%{q}%"),
                    Profile.name.ilike(f"%{q}%"),
                )
            )

        query = query.offset(offset).limit(per_page)
        result = await db.execute(query)
        users = list(result.scalars().all())

        count_conditions = [User.flood_ban_count > 0, User.is_flagged_spammer == True]
        if active_banned_ids:
            count_conditions.append(User.id.in_(list(active_banned_ids)))
        spammers_count = await db.scalar(
            select(func.count(User.id)).where(or_(*count_conditions))
        ) or len(active_banned_ids)

        premium_count = await db.scalar(
            select(func.count(User.id)).where(User.premium_until > now)
        ) or 0
        verified_count = await db.scalar(
            select(func.count(User.id)).where(User.email_verified == True)
        ) or 0

        from web.dependencies import generate_csrf_token
        token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

        return templates.TemplateResponse(
            "admin/users.html",
            {
                "request": request,
                "admin": admin,
                "users": users,
                "q": q,
                "page": page,
                "is_fake": is_fake,
                "filter_type": filter_type,
                "spammers_count": spammers_count,
                "premium_count": premium_count,
                "verified_count": verified_count,
                "active_banned_ids": active_banned_ids,
                "csrf_token": token_str,
            },
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error in list_users: {e}", exc_info=True)
        from web.dependencies import generate_csrf_token
        token_str = generate_csrf_token(request.cookies.get("admin_token", ""))
        return templates.TemplateResponse(
            "admin/users.html",
            {
                "request": request,
                "admin": admin,
                "users": [],
                "q": q,
                "page": 1,
                "is_fake": is_fake,
                "filter_type": filter_type,
                "spammers_count": 0,
                "csrf_token": token_str,
                "error_msg": str(e),
            },
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
        "Рейтинг (баллы)", "Анкета заполнена", "Анкета видна", "Активен",
        "Банов за флуд", "Спамер", "Дата регистрации",
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
            f"{prof.rating_score:.0f}" if prof and prof.rating_score is not None else "0",
            "Да" if prof and prof.is_complete else "Нет",
            "Да" if prof and prof.is_visible else "Нет",
            "Да" if u.is_active else "Заблокирован",
            u.flood_ban_count,
            "Да" if u.is_flagged_spammer else "Нет",
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
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    from bot.middlewares.throttling import get_redis, format_ban_ttl
    ban_ttl = 0
    ban_level = 1
    try:
        r = get_redis()
        ban_ttl = await r.ttl(f"temp_ban:{user_id}")
        raw_val = await r.get(f"temp_ban:{user_id}")
        raw_level = await r.get(f"flood_ban_level:{user_id}")
        if raw_val and str(raw_val).isdigit() and int(raw_val) > 0:
            ban_level = int(raw_val)
        elif raw_level and str(raw_level).isdigit() and int(raw_level) > 0:
            ban_level = int(raw_level)
        elif user and user.flood_ban_count > 0:
            ban_level = user.flood_ban_count
        else:
            ban_level = 1
    except Exception:
        ban_level = 1

    is_banned_val = bool(ban_ttl and ban_ttl > 0)
    if user and user.is_flagged_spammer and not is_banned_val:
        try:
            await db.execute(update(User).where(User.id == user_id).values(is_flagged_spammer=False))
            await db.commit()
            user.is_flagged_spammer = False
        except Exception:
            pass

    temp_ban_info = {
        "is_banned": is_banned_val,
        "ttl": max(0, ban_ttl if is_banned_val else 0),
        "time_left_str": format_ban_ttl(ban_ttl) if is_banned_val else None,
        "ban_level": ban_level,
    }

    # ─── Диагностика выдачи в ленте свайпов ───
    feed_diagnostic = {}
    try:
        from database.crud import get_next_profile, get_profile
        user_mode = getattr(user, "mode", ModeEnum.dating) or ModeEnum.dating
        next_cand = await get_next_profile(db, viewer_id=user_id, mode=user_mode)

        viewer_profile = await get_profile(db, user_id)

        # 1. Всего других активных пользователей
        total_active_others = (await db.scalar(
            select(func.count(User.id)).where(User.id != user_id, User.is_active == True)
        )) or 0

        # Условие завершенности и наличия реального имени и фото
        valid_name_and_photo = and_(
            Profile.name.isnot(None),
            Profile.name != "",
            Profile.name != "Студент",
            or_(
                Profile.avatar_file_id.isnot(None),
                Profile.career_avatar_file_id.isnot(None),
            ),
        )

        if user_mode == ModeEnum.career:
            is_complete_cond = (Profile.career_is_complete == True)
        elif user_mode == ModeEnum.projects:
            is_complete_cond = or_(Profile.project_is_complete == True, Profile.is_complete == True)
        else:
            is_complete_cond = (Profile.is_complete == True)

        ready_count = (await db.scalar(
            select(func.count(Profile.id))
            .join(User, Profile.user_id == User.id)
            .where(
                User.id != user_id,
                User.is_active == True,
                is_complete_cond,
                valid_name_and_photo,
                Profile.is_visible == True,
            )
        )) or 0

        hidden_profiles_count = (await db.scalar(
            select(func.count(Profile.id))
            .join(User, Profile.user_id == User.id)
            .where(
                User.id != user_id,
                User.is_active == True,
                is_complete_cond,
                valid_name_and_photo,
                Profile.is_visible == False,
            )
        )) or 0

        incomplete_profiles_count = max(0, total_active_others - ready_count - hidden_profiles_count)

        # Гендерные фильтры (для Знакомств)
        gender_filters = []
        if user_mode == ModeEnum.dating and viewer_profile:
            if viewer_profile.target_gender == "female":
                gender_filters.append(or_(Profile.gender == "female", Profile.gender.is_(None), Profile.gender == ""))
            elif viewer_profile.target_gender == "male":
                gender_filters.append(or_(Profile.gender == "male", Profile.gender.is_(None), Profile.gender == ""))

            if viewer_profile.gender == "male":
                gender_filters.append(
                    or_(
                        Profile.target_gender == "male",
                        Profile.target_gender == "all",
                        Profile.target_gender.is_(None),
                        Profile.target_gender == "",
                    )
                )
            elif viewer_profile.gender == "female":
                gender_filters.append(
                    or_(
                        Profile.target_gender == "female",
                        Profile.target_gender == "all",
                        Profile.target_gender.is_(None),
                        Profile.target_gender == "",
                    )
                )

        gender_mismatch_count = 0
        if gender_filters:
            gender_mismatch_count = (await db.scalar(
                select(func.count(Profile.id))
                .join(User, Profile.user_id == User.id)
                .where(
                    User.id != user_id,
                    User.is_active == True,
                    is_complete_cond,
                    valid_name_and_photo,
                    Profile.is_visible == True,
                    ~and_(*gender_filters),
                )
            )) or 0

        after_gender_count = max(0, ready_count - gender_mismatch_count)

        # Поисковые фильтры (возраст, курс, факультет)
        search_filters = []
        if viewer_profile:
            min_a = viewer_profile.filter_min_age
            max_a = viewer_profile.filter_max_age
            if min_a and max_a:
                search_filters.append(
                    or_(
                        Profile.age.is_(None),
                        and_(Profile.age >= min_a, Profile.age <= max_a),
                    )
                )

            min_y = viewer_profile.filter_min_year
            max_y = viewer_profile.filter_max_year
            if min_y and max_y:
                search_filters.append(
                    or_(
                        Profile.year.is_(None),
                        and_(Profile.year >= min_y, Profile.year <= max_y),
                    )
                )

            f_major = viewer_profile.filter_major
            if f_major and f_major != "all":
                search_filters.append(
                    or_(
                        Profile.major.is_(None),
                        Profile.major.ilike(f"%{f_major}%"),
                    )
                )

        search_mismatch_count = 0
        if search_filters:
            search_mismatch_count = (await db.scalar(
                select(func.count(Profile.id))
                .join(User, Profile.user_id == User.id)
                .where(
                    User.id != user_id,
                    User.is_active == True,
                    is_complete_cond,
                    valid_name_and_photo,
                    Profile.is_visible == True,
                    *gender_filters,
                    ~and_(*search_filters),
                )
            )) or 0

        after_search_count = max(0, after_gender_count - search_mismatch_count)

        # Подзапросы исключения
        reported_subq = exists(
            select(1).where(
                and_(
                    Report.reporter_id == user_id,
                    Report.reported_id == Profile.user_id,
                )
            )
        )
        liked_subq = exists(
            select(1).where(
                and_(
                    Swipe.from_user_id == user_id,
                    Swipe.to_user_id == Profile.user_id,
                    or_(Swipe.mode == user_mode, Swipe.mode.is_(None)),
                    Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
                )
            )
        )
        matched_subq = exists(
            select(1).where(
                and_(
                    Match.mode == user_mode,
                    or_(
                        and_(Match.user1_id == user_id, Match.user2_id == Profile.user_id),
                        and_(Match.user1_id == Profile.user_id, Match.user2_id == user_id),
                    ),
                )
            )
        )

        already_interacted_count = (await db.scalar(
            select(func.count(Profile.id))
            .join(User, Profile.user_id == User.id)
            .where(
                User.id != user_id,
                User.is_active == True,
                is_complete_cond,
                valid_name_and_photo,
                Profile.is_visible == True,
                *gender_filters,
                *search_filters,
                or_(liked_subq, matched_subq, reported_subq),
            )
        )) or 0

        eligible_count = max(0, after_search_count - already_interacted_count)

        # Свежие (ещё не свайпнутые)
        swiped_any_subq = exists(
            select(1).where(
                and_(
                    Swipe.from_user_id == user_id,
                    Swipe.to_user_id == Profile.user_id,
                    or_(Swipe.mode == user_mode, Swipe.mode.is_(None)),
                )
            )
        )
        fresh_count = (await db.scalar(
            select(func.count(Profile.id))
            .join(User, Profile.user_id == User.id)
            .where(
                User.id != user_id,
                User.is_active == True,
                is_complete_cond,
                valid_name_and_photo,
                Profile.is_visible == True,
                *gender_filters,
                *search_filters,
                ~reported_subq,
                ~liked_subq,
                ~matched_subq,
                ~swiped_any_subq,
            )
        )) or 0

        recycled_count = max(0, eligible_count - fresh_count)

        liked_by_user_count = (await db.scalar(
            select(func.count(Swipe.id))
            .where(Swipe.from_user_id == user_id, Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]))
        )) or 0

        matches_count = (await db.scalar(
            select(func.count(Match.id))
            .where(or_(Match.user1_id == user_id, Match.user2_id == user_id))
        )) or 0

        liked_this_user_count = (await db.scalar(
            select(func.count(Swipe.id))
            .where(Swipe.to_user_id == user_id, Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]))
        )) or 0

        feed_diagnostic = {
            "user_mode": str(user_mode.value if hasattr(user_mode, "value") else user_mode),
            "next_candidate": next_cand,
            "total_active_others": total_active_others,
            "ready_count": ready_count,
            "incomplete_profiles_count": incomplete_profiles_count,
            "hidden_profiles_count": hidden_profiles_count,
            "gender_mismatch_count": gender_mismatch_count,
            "search_mismatch_count": search_mismatch_count,
            "already_interacted_count": already_interacted_count,
            "eligible_count": eligible_count,
            "fresh_count": fresh_count,
            "recycled_count": recycled_count,
            "liked_by_user_count": liked_by_user_count,
            "matches_count": matches_count,
            "liked_this_user_count": liked_this_user_count,
        }
    except Exception as diag_err:
        feed_diagnostic = {"error": str(diag_err)}

    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/user_detail.html",
        {
            "request": request,
            "admin": admin,
            "user": user,
            "temp_ban_info": temp_ban_info,
            "feed_diagnostic": feed_diagnostic,
            "csrf_token": token_str,
        },
    )


@router.post("/users/{user_id}/unban-flood", dependencies=[Depends(check_csrf)])
async def unban_user_flood(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Досрочное снятие бана за флуд в Redis и сброс статуса спамера."""
    from bot.middlewares.throttling import get_redis
    try:
        r = get_redis()
        await r.delete(
            f"temp_ban:{user_id}",
            f"flood_viols:{user_id}",
            f"cb_viols:{user_id}",
            f"warn_throttle:{user_id}",
            f"flood_ban_level:{user_id}",
        )
    except Exception:
        pass

    await db.execute(
        update(User).where(User.id == user_id).values(is_active=True, is_flagged_spammer=False)
    )
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="unban_flood", target_type="user", target_id=str(user_id),
        details="Досрочно снята блокировка за спам/флуд", ip_address=client_ip
    )

    # Уведомляем пользователя в Telegram
    try:
        from aiogram import Bot
        from bot.config import settings
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(
            user_id,
            "🟢 <b>Блокировка за частые запросы снята администратором!</b>\n\nВы снова можете полноценно пользоваться ботом (/start).",
            parse_mode="HTML"
        )
        await bot.session.close()
    except Exception:
        pass

    return RedirectResponse(f"/admin/users/{user_id}?unbanned_flood=1", status_code=302)


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
    from bot.middlewares.throttling import get_redis
    try:
        r = get_redis()
        await r.delete(
            f"temp_ban:{user_id}",
            f"flood_viols:{user_id}",
            f"cb_viols:{user_id}",
            f"warn_throttle:{user_id}",
            f"flood_ban_level:{user_id}",
        )
    except Exception:
        pass

    await db.execute(update(User).where(User.id == user_id).values(is_active=True, is_flagged_spammer=False))
    await db.execute(update(Profile).where(Profile.user_id == user_id).values(is_visible=True))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="user_unban", target_type="user", target_id=str(user_id),
        details="Пользователь разблокирован администратором (видимость анкеты восстановлена)", ip_address=client_ip
    )

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/toggle-visibility", dependencies=[Depends(check_csrf)])
async def toggle_user_visibility(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Переключение видимости анкеты в поиске (Profile.is_visible)."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    new_val = not profile.is_visible
    profile.is_visible = new_val
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="toggle_visibility", target_type="user", target_id=str(user_id),
        details=f"Видимость анкеты в поиске изменена на: {'Видима' if new_val else 'Скрыта'}",
        ip_address=client_ip
    )

    return RedirectResponse(f"/admin/users/{user_id}?visibility_changed=1", status_code=302)


@router.post("/users/{user_id}/toggle-complete", dependencies=[Depends(check_csrf)])
async def toggle_user_complete(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Переключение флага завершенности анкеты (Profile.is_complete)."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    new_val = not profile.is_complete
    profile.is_complete = new_val
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="toggle_complete", target_type="user", target_id=str(user_id),
        details=f"Статус завершенности анкеты изменен на: {'Заполнена' if new_val else 'Не заполнена'}",
        ip_address=client_ip
    )

    return RedirectResponse(f"/admin/users/{user_id}?complete_changed=1", status_code=302)


@router.post("/users/restore-all-visibility", dependencies=[Depends(check_csrf)])
async def restore_all_visibility(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Массовое восстановление видимости (is_visible=True) и заполненности (is_complete=True)
    для всех активных (незаблокированных) пользователей.
    Гарантирует присутствие всех активных анкет в поиске и устраняет пустые ленты свайпов.
    """
    subq = select(User.id).where(User.is_active == True)

    # 1. Восстанавливаем видимость для тех, у кого есть валидное фото и имя
    valid_profile_filter = and_(
        Profile.name.isnot(None),
        Profile.name != "",
        Profile.name != "Студент",
        or_(
            Profile.avatar_file_id.isnot(None),
            Profile.career_avatar_file_id.isnot(None),
        ),
    )

    vis_res = await db.execute(
        update(Profile)
        .where(
            Profile.user_id.in_(subq),
            Profile.is_visible == False,
            valid_profile_filter,
        )
        .values(is_visible=True)
    )
    restored_vis = vis_res.rowcount

    # 2. Восстанавливаем заполненность только для анкет с реальными данными
    comp_res = await db.execute(
        update(Profile)
        .where(
            Profile.user_id.in_(subq),
            Profile.is_complete == False,
            valid_profile_filter,
        )
        .values(is_complete=True)
    )
    restored_comp = comp_res.rowcount

    # 3. Деактивируем анкеты-пустышки (без фото или без имени)
    ghost_res = await db.execute(
        update(Profile)
        .where(
            Profile.user_id.in_(subq),
            or_(
                Profile.name.is_(None),
                Profile.name == "",
                Profile.name == "Студент",
                and_(Profile.avatar_file_id.is_(None), Profile.career_avatar_file_id.is_(None)),
            ),
            or_(Profile.is_complete == True, Profile.is_visible == True),
        )
        .values(is_complete=False, is_visible=False)
    )
    ghosts_hidden = ghost_res.rowcount
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db,
        admin,
        action="bulk_restore_visibility",
        target_type="system",
        target_id="profiles",
        details=f"Массовое восстановление анкет: видимость={restored_vis}, заполненность={restored_comp}, скрыто пустышек={ghosts_hidden}",
        ip_address=client_ip,
    )

    return RedirectResponse(
        f"/admin/users?restored_count={restored_vis}&restored_comp={restored_comp}&ghosts_hidden={ghosts_hidden}",
        status_code=302,
    )


@router.post("/users/hide-empty-profiles", dependencies=[Depends(check_csrf)])
async def hide_empty_profiles_admin(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Скрыть и снять заполненность со всех анкет-пустышек (где нет фото или имени)."""
    subq = select(User.id).where(User.is_active == True)
    update_res = await db.execute(
        update(Profile)
        .where(
            Profile.user_id.in_(subq),
            or_(
                Profile.name.is_(None),
                Profile.name == "",
                Profile.name == "Студент",
                and_(Profile.avatar_file_id.is_(None), Profile.career_avatar_file_id.is_(None)),
            ),
            or_(Profile.is_complete == True, Profile.is_visible == True),
        )
        .values(is_complete=False, is_visible=False)
    )
    hidden_count = update_res.rowcount
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db,
        admin,
        action="hide_empty_profiles",
        target_type="system",
        target_id="profiles",
        details=f"Скрыто {hidden_count} анкет-пустышек без фото/имени",
        ip_address=client_ip,
    )

    return RedirectResponse(
        f"/admin/users?hidden_empty_count={hidden_count}",
        status_code=302,
    )


@router.post("/users/reset-all-swipes", dependencies=[Depends(check_csrf)])
async def reset_all_swipes_admin(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сбросить историю свайпов и взаимных мэтчей для ВСЕХ пользователей (для тестирования)."""
    await db.execute(delete(Swipe))
    await db.execute(delete(Match))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db,
        admin,
        action="bulk_reset_swipes",
        target_type="system",
        target_id="swipes_and_matches",
        details="Полный сброс истории всех свайпов и мэтчей администратором",
        ip_address=client_ip,
    )

    return RedirectResponse("/admin/users?all_swipes_reset=1", status_code=302)


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
                "✅ <b>Ваш студенческий статус подтверждён модератором!</b>\n\n"
                "Вам присвоен бейдж <b>🎓 [Верифицирован]</b> и начислено +100 баллов рейтинга!",
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            pass

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/unverify", dependencies=[Depends(check_csrf)])
async def unverify_user_manually(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Снятие статуса верификации пользователя администратором."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        await db.execute(update(User).where(User.id == user_id).values(email_verified=False))
        await db.commit()

        client_ip = request.client.host if request.client else None
        await log_admin_action(
            db, admin, action="user_unverified", target_type="user", target_id=str(user_id),
            details="Статус верификации студента снят администратором",
            ip_address=client_ip,
        )

    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/set-premium", dependencies=[Depends(check_csrf)])
async def set_user_premium_admin(
    user_id: int,
    request: Request,
    days: int = Form(default=30),
    action: str = Form(default="set"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Выдать или отозвать Premium-статус пользователя администратором."""
    from database.crud import set_user_premium, revoke_user_premium
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        client_ip = request.client.host if request.client else None
        if action == "revoke":
            await revoke_user_premium(db, user_id)
            await log_admin_action(
                db, admin, action="premium_revoked", target_type="user", target_id=str(user_id),
                details="Премиум-статус отозван администратором",
                ip_address=client_ip,
            )
            try:
                from aiogram import Bot
                from bot.config import settings
                bot = Bot(token=settings.BOT_TOKEN)
                await bot.send_message(
                    user_id,
                    "ℹ️ <b>Ваш Премиум-статус был отключён администрацией.</b>",
                    parse_mode="HTML",
                )
                await bot.session.close()
            except Exception:
                pass
        else:
            new_until = await set_user_premium(db, user_id, days=days)
            date_str = new_until.strftime("%d.%m.%Y %H:%M")
            await log_admin_action(
                db, admin, action="premium_granted", target_type="user", target_id=str(user_id),
                details=f"Премиум-статус установлен на {days} дн. (до {date_str})",
                ip_address=client_ip,
            )
            try:
                from aiogram import Bot
                from bot.config import settings
                bot = Bot(token=settings.BOT_TOKEN)
                await bot.send_message(
                    user_id,
                    f"💎 <b>Вам подключён Премиум-профиль!</b>\n\n"
                    f"Срок действия: до <b>{date_str}</b> (+{days} дн.)\n"
                    f"Теперь ваша анкета показывается с наивысшим приоритетом в ленте, "
                    f"вам доступен бейдж <b>[Премиум]</b> и раздел «💌 Кто меня лайкнул»!",
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
    """Сбросить исходящую историю свайпов и мэтчей пользователя."""
    await db.execute(delete(Swipe).where(Swipe.from_user_id == user_id))
    await db.execute(delete(Match).where(or_(Match.user1_id == user_id, Match.user2_id == user_id)))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="reset_swipes", target_type="user", target_id=str(user_id),
        details="Исходящие свайпы и мэтчи пользователя сброшены администратором",
        ip_address=client_ip,
    )

    return RedirectResponse(f"/admin/users/{user_id}?swipes_reset=1", status_code=302)


@router.post("/users/{user_id}/reset-all-interactions", dependencies=[Depends(check_csrf)])
async def reset_user_all_interactions_admin(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сбросить ВСЕ свайпы (и исходящие, и входящие) и взаимные мэтчи пользователя."""
    await db.execute(delete(Swipe).where(or_(Swipe.from_user_id == user_id, Swipe.to_user_id == user_id)))
    await db.execute(delete(Match).where(or_(Match.user1_id == user_id, Match.user2_id == user_id)))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="reset_all_interactions", target_type="user", target_id=str(user_id),
        details="Полный сброс всех связей (входящие/исходящие свайпы и мэтчи) пользователя",
        ip_address=client_ip,
    )

    return RedirectResponse(f"/admin/users/{user_id}?all_interactions_reset=1", status_code=302)


@router.post("/users/{user_id}/activate-profile", dependencies=[Depends(check_csrf)])
async def activate_profile_admin(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сделать анкету активной, видимой и заполненной (1 клик)."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile:
        profile.is_visible = True
        profile.is_complete = True
        if profile.career_goal or profile.career_skills:
            profile.career_is_complete = True
        await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="activate_profile", target_type="user", target_id=str(user_id),
        details="Анкета активирована (is_visible=True, is_complete=True) администратором",
        ip_address=client_ip,
    )

    return RedirectResponse(f"/admin/users/{user_id}?activated=1", status_code=302)


@router.post("/users/{user_id}/reset-filters", dependencies=[Depends(check_csrf)])
async def reset_user_filters_admin(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Сбросить поисковые фильтры пользователя до стандартных значений."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile:
        profile.filter_min_age = 16
        profile.filter_max_age = 35
        profile.filter_min_year = 1
        profile.filter_max_year = 6
        profile.filter_major = None
        profile.target_gender = "all"
        await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="reset_filters", target_type="user", target_id=str(user_id),
        details="Поисковые фильтры пользователя сброшены до стандартных",
        ip_address=client_ip,
    )

    return RedirectResponse(f"/admin/users/{user_id}?filters_reset=1", status_code=302)


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


@router.post("/users/delete-all-test", dependencies=[Depends(check_csrf)])
async def delete_all_test_users(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Удаляет все тестовые и фейковые анкеты из базы данных."""
    from sqlalchemy import text
    statements = [
        "UPDATE users SET referrer_id = NULL WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100;",
        "DELETE FROM swipes WHERE from_user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100) OR to_user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM matches WHERE user1_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100) OR user2_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM achievements WHERE user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM payments WHERE user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM reports WHERE reporter_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100) OR reported_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM data_export_requests WHERE user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM email_tokens WHERE user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM promo_activations WHERE user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM profiles WHERE user_id IN (SELECT id FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100);",
        "DELETE FROM users WHERE is_fake = TRUE OR id BETWEEN 900000001 AND 900000100;",
    ]
    for stmt in statements:
        try:
            await db.execute(text(stmt))
        except Exception:
            pass
    await db.commit()

    await log_admin_action(
        db, admin, action="delete_all_test_users", target_type="user",
        details="Удалены все тестовые и фейковые анкеты",
    )
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_single_user(
    user_id: int,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Каскадное удаление конкретного пользователя."""
    from sqlalchemy import text
    statements = [
        f"UPDATE users SET referrer_id = NULL WHERE referrer_id = {user_id};",
        f"DELETE FROM swipes WHERE from_user_id = {user_id} OR to_user_id = {user_id};",
        f"DELETE FROM matches WHERE user1_id = {user_id} OR user2_id = {user_id};",
        f"DELETE FROM achievements WHERE user_id = {user_id};",
        f"DELETE FROM payments WHERE user_id = {user_id};",
        f"DELETE FROM reports WHERE reporter_id = {user_id} OR reported_id = {user_id};",
        f"DELETE FROM data_export_requests WHERE user_id = {user_id};",
        f"DELETE FROM email_tokens WHERE user_id = {user_id};",
        f"DELETE FROM promo_activations WHERE user_id = {user_id};",
        f"DELETE FROM profiles WHERE user_id = {user_id};",
        f"DELETE FROM users WHERE id = {user_id};",
    ]
    for stmt in statements:
        try:
            await db.execute(text(stmt))
        except Exception:
            pass
    await db.commit()

    await log_admin_action(
        db, admin, action="delete_user", target_type="user", target_id=str(user_id),
        details=f"Удален пользователь #{user_id}",
    )
    return RedirectResponse("/admin/users", status_code=302)
