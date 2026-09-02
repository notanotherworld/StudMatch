"""
Роутер Telegram Mini App (WebApp) для StudMatch.
Полнофункциональный SPA: авторизация через initData, свайпы, мэтчи, профиль, медиа-прокси.
"""
import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from urllib.parse import parse_qsl

import os
import aiohttp
from fastapi import APIRouter, Request, Depends, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import selectinload

from bot.config import settings
from web.dependencies import get_db, SECRET, ALGORITHM
import jwt
from database.models import (
    User, Profile, University, Swipe, Match, SwipeAction, ModeEnum, InterestTag,
    Report, ReportStatus
)
from database.crud import (
    get_user, get_profile, get_next_profile, create_swipe,
    get_user_matches, get_incoming_likes, get_incoming_likes_count,
    deduct_superlike
)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

STUDENT_SESSION_TTL_DAYS = 30

PHOTO_CACHE_DIR = os.path.abspath("web/static/uploads/cache")
os.makedirs(PHOTO_CACHE_DIR, exist_ok=True)
DEFAULT_FALLBACK_AVATAR = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"


def resolve_photo_url(photo_id: Optional[str]) -> Optional[str]:
    """Преобразует идентификатор фото в валидный HTTP/HTTPS URL или путь к медиа-прокси."""
    if not photo_id or not str(photo_id).strip():
        return None
    p_str = str(photo_id).strip()
    if p_str.lower() in ("none", "null", "undefined", "false", ""):
        return None
    if p_str.startswith("http://") or p_str.startswith("https://"):
        return p_str
    if p_str.startswith("/static/") or p_str.startswith("/uploads/"):
        return p_str
    if p_str.startswith("static/") or p_str.startswith("uploads/"):
        return f"/{p_str}"
    return f"/api/webapp/photo/{p_str}"


# ─── Валидация Telegram WebApp initData ──────────────────────
def verify_telegram_init_data(init_data: str, bot_token: str) -> Optional[Dict[str, Any]]:
    """
    Криптографическая проверка подписи initData от Telegram WebApp (HMAC-SHA256).
    Возвращает dict с данными пользователя или None при невалидной подписи.
    """
    if not init_data or not bot_token:
        return None
    try:
        init_data = init_data.strip().lstrip("?").lstrip("#")
        if "tgWebAppData=" in init_data:
            outer_params = dict(parse_qsl(init_data, keep_blank_values=True))
            init_data = outer_params.get("tgWebAppData") or outer_params.get("#tgWebAppData") or init_data

        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            logger.warning("Telegram initData missing 'hash' parameter")
            return None
        received_hash = parsed_data.pop("hash")

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )

        clean_token = bot_token.strip()
        secret_key = hmac.new(
            key=b"WebAppData",
            msg=clean_token.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(calculated_hash, received_hash):
            user_raw = parsed_data.get("user")
            if user_raw:
                return json.loads(user_raw)
        else:
            logger.warning(
                f"Telegram initData hash mismatch: calc={calculated_hash[:10]}... vs rec={received_hash[:10]}..."
            )
        return None
    except Exception as e:
        logger.warning(f"Error validating Telegram initData: {e}")
        return None


def create_student_token(user_id: int, tg_username: Optional[str] = None) -> str:
    """Генерация JWT-токена для студента."""
    expire = datetime.now(timezone.utc) + timedelta(days=STUDENT_SESSION_TTL_DAYS)
    payload = {
        "user_id": user_id,
        "tg_username": tg_username,
        "role": "student",
        "exp": expire,
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


async def get_current_student(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Зависимость: извлекает текущего студента из Bearer токена или cookie."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    if not token:
        token = request.cookies.get("student_token")

    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация Telegram WebApp")

    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Неверный токен")
    except Exception:
        raise HTTPException(status_code=401, detail="Срок действия сессии истек")

    user = await get_user(db, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь заблокирован или не найден")
    return user


# ─── HTML Страница WebApp ─────────────────────────────────────
@router.api_route("/app", methods=["GET", "HEAD"], response_class=HTMLResponse)
@router.api_route("/webapp", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def webapp_page(request: Request):
    """Отдача основного HTML5 SPA приложения для Telegram WebApp."""
    return templates.TemplateResponse(
        "webapp.html",
        {
            "request": request,
            "bot_username": settings.BOT_USERNAME,
        }
    )


# ─── API: Авторизация через initData ─────────────────────────
class WebAppAuthRequest(BaseModel):
    init_data: str


@router.post("/api/webapp/auth")
async def webapp_auth(
    payload: WebAppAuthRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Авторизация в Telegram WebApp по initData.
    Если пользователь новый — создает учетную запись.
    """
    tg_user = verify_telegram_init_data(payload.init_data, settings.BOT_TOKEN)
    
    # Для локальной разработки в режиме отладки
    if not tg_user and settings.BOT_TOKEN.startswith("test_") and payload.init_data == "dev_mock":
        tg_user = {"id": 100001, "username": "test_student", "first_name": "Тестовый"}

    if not tg_user:
        raise HTTPException(status_code=403, detail="Неверная подпись Telegram initData")

    user_id = int(tg_user["id"])
    tg_username = tg_user.get("username")

    from database.crud import get_or_create_user
    user = await get_or_create_user(db, user_id=user_id, tg_username=tg_username)

    is_superadmin = (user.id == settings.SUPERADMIN_ID or user.id in settings.admin_ids)
    if is_superadmin:
        user.is_premium = True
        user.email_verified = True
        user.superlike_balance = max(user.superlike_balance or 0, 9999)
        await db.commit()

    token = create_student_token(user.id, user.tg_username)
    response.set_cookie(
        key="student_token",
        value=token,
        httponly=True,
        max_age=STUDENT_SESSION_TTL_DAYS * 86400,
        samesite="none",
        secure=True,
    )

    profile = user.profile
    return {
        "status": "ok",
        "token": token,
        "user": {
            "id": user.id,
            "username": user.tg_username,
            "is_premium": user.is_premium,
            "is_verified": user.is_verified,
            "superlike_balance": user.superlike_balance,
            "mode": user.mode.value if user.mode else "dating",
            "has_profile": profile is not None and bool(profile.name),
            "is_superadmin": is_superadmin,
        },
    }


# ─── API: Лента свайпов (Feed) ───────────────────────────────
@router.get("/api/webapp/feed")
async def webapp_feed(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Возвращает список анкет кандидатов для свайпов в WebApp.
    """
    mode = student.mode or ModeEnum.dating

    # Получаем пачку до 10 кандидатов
    candidates = []
    seen_ids = set()

    for _ in range(10):
        cand_profile = await get_next_profile(
            db, viewer_id=student.id, mode=mode, exclude_ids=seen_ids
        )
        if not cand_profile:
            break
        seen_ids.add(cand_profile.user_id)
        candidates.append(cand_profile)

    # Если в режиме Карьеры пока нет анкет с заполненной карьерой — показываем общие студенческие анкеты
    if not candidates and mode == ModeEnum.career:
        for _ in range(10):
            cand_profile = await get_next_profile(
                db, viewer_id=student.id, mode=ModeEnum.dating, exclude_ids=seen_ids
            )
            if not cand_profile:
                break
            seen_ids.add(cand_profile.user_id)
            candidates.append(cand_profile)

    # Загружаем теги интересов
    all_tag_ids = set()
    for p in candidates:
        if p.interest_ids:
            all_tag_ids.update(p.interest_ids)

    tags_map = {}
    if all_tag_ids:
        tag_res = await db.execute(select(InterestTag).where(InterestTag.id.in_(all_tag_ids)))
        for t in tag_res.scalars().all():
            tags_map[t.id] = {"id": t.id, "name": t.name, "emoji": t.emoji}

    result = []
    for p in candidates:
        u = p.user
        photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])
        if mode == ModeEnum.career and p.career_avatar_file_id and p.career_avatar_file_id not in photos:
            photos = [p.career_avatar_file_id] + photos

        # Преобразуем фото в URL медиа-прокси или прямые ссылки
        photo_urls = [resolve_photo_url(pid) for pid in photos if resolve_photo_url(pid)]
        if not photo_urls:
            photo_urls = [DEFAULT_FALLBACK_AVATAR]

        cand_tags = [tags_map[tid] for tid in (p.interest_ids or []) if tid in tags_map]

        univ_name = u.university.short_name if (u and u.university) else ""

        result.append({
            "user_id": p.user_id,
            "name": p.name or "Студент",
            "age": p.age,
            "year": p.year,
            "major": p.major or "",
            "university": univ_name,
            "goal": p.goal or "",
            "custom_interests": p.custom_interests or "",
            "tags": cand_tags,
            "photos": photo_urls,
            "rating_score": round(p.rating_score or 0.0, 1),
            "is_verified": getattr(u, "email_verified", False),
            "is_premium": getattr(u, "is_premium", False),
            # Специфика карьеры
            "career_goal": p.career_goal if mode == ModeEnum.career else None,
            "career_skills": p.career_skills if mode == ModeEnum.career else None,
            "career_custom_skills": p.career_custom_skills if mode == ModeEnum.career else None,
            "career_portfolio_url": p.career_portfolio_url if mode == ModeEnum.career else None,
            "career_work_format": p.career_work_format if mode == ModeEnum.career else None,
        })

    return {"status": "ok", "count": len(result), "profiles": result}


# ─── API: Свайп карточки ─────────────────────────────────────
class WebAppSwipeRequest(BaseModel):
    target_id: int
    action: str  # like, skip, superlike
    comment: Optional[str] = None


@router.post("/api/webapp/swipe")
async def webapp_swipe(
    payload: WebAppSwipeRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Сохранение свайпа (Лайк, Скип, Суперлайк) через WebApp.
    При взаимном лайке возвращает статус match=True и данные партнёра.
    """
    action_map = {
        "like": SwipeAction.like,
        "superlike": SwipeAction.superlike,
        "skip": SwipeAction.skip,
    }
    action = action_map.get(payload.action.lower(), SwipeAction.skip)

    # Проверка баланса суперлайков
    if action == SwipeAction.superlike:
        if student.superlike_balance <= 0:
            raise HTTPException(status_code=400, detail="Недостаточно суперлайков на балансе")
        deducted = await deduct_superlike(db, student.id)
        if not deducted:
            raise HTTPException(status_code=400, detail="Недостаточно суперлайков")

    is_match = await create_swipe(
        db,
        from_id=student.id,
        to_id=payload.target_id,
        action=action,
        comment=payload.comment,
    )

    match_data = None
    if is_match:
        partner = await get_user(db, payload.target_id)
        if partner:
            p_profile = partner.profile
            p_photos = list(p_profile.photos) if (p_profile and p_profile.photos) else ([p_profile.avatar_file_id] if (p_profile and p_profile.avatar_file_id) else [])
            first_p = p_photos[0] if p_photos else None
            match_data = {
                "user_id": partner.id,
                "name": p_name,
                "tg_username": partner.tg_username,
                "photo_url": resolve_photo_url(first_p) or DEFAULT_FALLBACK_AVATAR,
            }

            # Отправка Telegram-уведомления партнеру в фоновом режиме
            try:
                from aiogram import Bot
                bot = Bot(token=settings.BOT_TOKEN)
                my_name = student.profile.name if (student.profile and student.profile.name) else "Студент"
                my_username = f"@{student.tg_username}" if student.tg_username else "(нет username)"
                await bot.send_message(
                    chat_id=partner.id,
                    text=(
                        f"🎉 <b>МЭТЧ в StudMatch WebApp!</b>\n\n"
                        f"Вы с <b>{my_name}</b> понравились друг другу!\n"
                        f"Telegram: <b>{my_username}</b>"
                    ),
                    parse_mode="HTML"
                )
                await bot.session.close()
            except Exception as e:
                logger.warning(f"Failed to notify match partner via bot: {e}")

    return {
        "status": "ok",
        "action": action.value,
        "is_match": is_match,
        "match": match_data,
        "superlike_balance": student.superlike_balance,
    }


# ─── API: Список мэтчей (Matches) ────────────────────────────
@router.get("/api/webapp/matches")
async def webapp_matches(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Список всех взаимных мэтчей студента."""
    matches = await get_user_matches(db, student.id)
    result = []

    for m, partner in matches:
        p = partner.profile
        raw_name = p.name if (p and p.name) else "Студент"
        photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
        first_p = photos[0] if photos else None
        photo_url = resolve_photo_url(first_p) or DEFAULT_FALLBACK_AVATAR

        univ_name = partner.university.short_name if partner.university else ""
        date_str = m.created_at.strftime("%d.%m") if m.created_at else ""

        result.append({
            "user_id": partner.id,
            "name": raw_name,
            "tg_username": partner.tg_username,
            "photo_url": photo_url,
            "year": p.year if p else None,
            "major": p.major if p else None,
            "university": univ_name,
            "goal": p.goal if p else None,
            "created_at": date_str,
            "is_verified": getattr(partner, "email_verified", False),
            "is_premium": getattr(partner, "is_premium", False),
        })

    return {"status": "ok", "count": len(result), "matches": result}


# ─── API: Входящие симпатии (Incoming Likes) ─────────────────
@router.get("/api/webapp/incoming_likes")
async def webapp_incoming_likes(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Входящие лайки (для Премиум пользователей — список, для обычных — тизер).
    """
    count = await get_incoming_likes_count(db, student.id)
    is_prem = student.is_premium

    likes_list = []
    if is_prem and count > 0:
        raw_likes = await get_incoming_likes(db, student.id, limit=30)
        for lk in raw_likes:
            c = lk.from_user
            p = c.profile
            photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
            first_p = photos[0] if photos else None
            likes_list.append({
                "user_id": c.id,
                "name": p.name if (p and p.name) else "Студент",
                "age": p.age if p else None,
                "year": p.year if p else None,
                "university": c.university.short_name if c.university else "",
                "photo_url": resolve_photo_url(first_p) or DEFAULT_FALLBACK_AVATAR,
                "is_superlike": lk.action == SwipeAction.superlike,
                "comment": lk.comment,
            })

    return {
        "status": "ok",
        "is_premium": is_prem,
        "count": count,
        "likes": likes_list,
    }


# ─── API: Профиль текущего студента ──────────────────────────
@router.get("/api/webapp/profile")
async def webapp_profile(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Данные текущего профиля для вкладки Profile."""
    p = student.profile
    photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
    photo_urls = [resolve_photo_url(pid) for pid in photos if resolve_photo_url(pid)]
    if not photo_urls:
        photo_urls = [DEFAULT_FALLBACK_AVATAR]

    tags = []
    if p and p.interest_ids:
        tag_res = await db.execute(select(InterestTag).where(InterestTag.id.in_(p.interest_ids)))
        for t in tag_res.scalars().all():
            tags.append({"id": t.id, "name": t.name, "emoji": t.emoji})

    is_superadmin = (student.id == settings.SUPERADMIN_ID or student.id in settings.admin_ids)
    if is_superadmin:
        student.is_premium = True
        student.email_verified = True
        student.superlike_balance = max(student.superlike_balance or 0, 9999)
        await db.commit()

    return {
        "status": "ok",
        "user": {
            "id": student.id,
            "username": student.tg_username,
            "is_verified": student.is_verified,
            "is_premium": student.is_premium,
            "superlike_balance": student.superlike_balance,
            "mode": student.mode.value if student.mode else "dating",
            "name": p.name if p else "",
            "age": p.age if p else None,
            "year": p.year if p else None,
            "major": p.major if p else "",
            "university": student.university.name if student.university else "",
            "goal": p.goal if p else "",
            "custom_interests": p.custom_interests if p else "",
            "tags": tags,
            "photos": photo_urls,
            "rating_score": round(p.rating_score or 0.0, 1) if p else 0.0,
            "is_superadmin": is_superadmin,
        }
    }


# ─── API: Переключение режима (Знакомства / Карьера) ─────────
class ToggleModeRequest(BaseModel):
    mode: str  # dating или career


@router.post("/api/webapp/profile/mode")
async def webapp_toggle_mode(
    payload: ToggleModeRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Смена активного режима студента."""
    new_mode = ModeEnum.career if payload.mode == "career" else ModeEnum.dating
    student.mode = new_mode
    await db.commit()
    return {"status": "ok", "mode": new_mode.value}


# ─── API: Поисковые фильтры (Возраст, Курс, Факультет) ────────
class WebAppFiltersRequest(BaseModel):
    min_age: int = 16
    max_age: int = 35
    min_year: int = 1
    max_year: int = 6
    major: Optional[str] = "all"


@router.get("/api/webapp/filters")
async def webapp_get_filters(
    student: User = Depends(get_current_student),
):
    """Получить текущие сохраненные фильтры пользователя."""
    p = student.profile
    return {
        "status": "ok",
        "min_age": p.filter_min_age if (p and p.filter_min_age) else 16,
        "max_age": p.filter_max_age if (p and p.filter_max_age) else 35,
        "min_year": p.filter_min_year if (p and p.filter_min_year) else 1,
        "max_year": p.filter_max_year if (p and p.filter_max_year) else 6,
        "major": p.filter_major if (p and p.filter_major) else "all",
    }


@router.post("/api/webapp/filters")
async def webapp_save_filters(
    payload: WebAppFiltersRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить фильтры поиска (возраст, курс, факультет)."""
    p = student.profile
    if p:
        p.filter_min_age = max(16, min(50, payload.min_age))
        p.filter_max_age = max(payload.min_age, min(50, payload.max_age))
        p.filter_min_year = max(1, min(6, payload.min_year))
        p.filter_max_year = max(payload.min_year, min(6, payload.max_year))
        p.filter_major = None if payload.major in ("all", "", None) else payload.major.strip()
        await db.commit()
    return {"status": "ok"}


# ─── API: Жалоба на анкету (Report) ──────────────────────────
class WebAppReportRequest(BaseModel):
    reported_id: int
    reason: str


@router.post("/api/webapp/report")
async def webapp_report_user(
    payload: WebAppReportRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Отправить жалобу на пользователя и исключить его из выдачи."""
    if payload.reported_id == student.id:
        raise HTTPException(status_code=400, detail="Нельзя пожаловаться на самого себя")

    exist_report = await db.scalar(
        select(Report).where(
            Report.reporter_id == student.id,
            Report.reported_id == payload.reported_id,
        )
    )
    if not exist_report:
        import uuid
        db.add(
            Report(
                id=uuid.uuid4(),
                reporter_id=student.id,
                reported_id=payload.reported_id,
                reason=payload.reason[:500],
                status=ReportStatus.pending,
            )
        )
        await db.commit()
    return {"status": "ok"}


# ─── API: Детальная анкета пользователя (для листа и мэтчей) ─
@router.get("/api/webapp/user/{user_id}")
async def webapp_get_user_details(
    user_id: int,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает полную карточку любого студента (для модалки и мэтчей)."""
    target = await get_user(db, user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    p = target.profile
    photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
    if p and p.career_avatar_file_id and p.career_avatar_file_id not in photos:
        photos.append(p.career_avatar_file_id)

    photo_urls = [resolve_photo_url(pid) for pid in photos if resolve_photo_url(pid)]
    if not photo_urls:
        photo_urls = [DEFAULT_FALLBACK_AVATAR]

    tags = []
    if p and p.interest_ids:
        tag_res = await db.execute(select(InterestTag).where(InterestTag.id.in_(p.interest_ids)))
        for t in tag_res.scalars().all():
            tags.append({"id": t.id, "name": t.name, "emoji": t.emoji})

    return {
        "status": "ok",
        "user": {
            "user_id": target.id,
            "name": p.name if p else "Студент",
            "age": p.age if p else None,
            "year": p.year if p else None,
            "major": p.major if p else "",
            "university": target.university.name if target.university else "",
            "goal": p.goal if p else "",
            "custom_interests": p.custom_interests if p else "",
            "tags": tags,
            "photos": photo_urls,
            "rating_score": round(p.rating_score or 0.0, 1) if p else 0.0,
            "is_verified": getattr(target, "email_verified", False),
            "is_premium": getattr(target, "is_premium", False),
            "tg_username": target.tg_username,
            # Карьерные параметры
            "career_goal": p.career_goal if p else None,
            "career_skills": p.career_skills if p else None,
            "career_custom_skills": p.career_custom_skills if p else None,
            "career_portfolio_url": p.career_portfolio_url if p else None,
            "career_work_format": p.career_work_format if p else None,
        }
    }


@router.post("/api/webapp/reset_swipes")
async def webapp_reset_swipes(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Сбросить историю свайпов для повторного просмотра анкет."""
    from sqlalchemy import delete
    await db.execute(delete(Swipe).where(Swipe.from_user_id == student.id))
    await db.commit()
    logger.info(f"User {student.id} reset their swipes in WebApp")
    return {"status": "ok"}


# ─── API: Админ-панель для Главного Администратора (ID: 149620234) ───
async def require_superadmin(student: User = Depends(get_current_student)) -> User:
    if student.id != settings.SUPERADMIN_ID and student.id not in settings.admin_ids:
        raise HTTPException(status_code=403, detail="Доступ только для главного администратора")
    return student


@router.get("/api/webapp/admin/stats")
async def webapp_admin_stats(
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Живая статистика сервиса."""
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    total_users = await db.scalar(select(func.count(User.id))) or 0
    active_24h = await db.scalar(
        select(func.count(User.id)).where(User.last_active_at >= yesterday)
    ) or 0
    total_matches = await db.scalar(select(func.count(Match.id))) or 0
    total_swipes = await db.scalar(select(func.count(Swipe.id))) or 0
    pending_reports = await db.scalar(
        select(func.count(Report.id)).where(Report.status == ReportStatus.pending)
    ) or 0

    return {
        "status": "ok",
        "stats": {
            "total_users": total_users,
            "active_24h": active_24h,
            "total_matches": total_matches,
            "total_swipes": total_swipes,
            "pending_reports": pending_reports,
        },
    }


@router.get("/api/webapp/admin/users/search")
async def webapp_admin_search_user(
    q: str,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Поиск пользователя по ID или @username."""
    q_clean = q.strip().lstrip("@")
    query = select(User).options(selectinload(User.profile), selectinload(User.university))

    if q_clean.isdigit():
        query = query.where(or_(User.id == int(q_clean), User.tg_username.ilike(f"%{q_clean}%")))
    else:
        query = query.where(User.tg_username.ilike(f"%{q_clean}%"))

    result = await db.execute(query.limit(10))
    users = result.scalars().all()

    found = []
    for u in users:
        p = u.profile
        found.append({
            "id": u.id,
            "username": u.tg_username,
            "name": p.name if p else "Без имени",
            "age": p.age if p else None,
            "university": u.university.name if u.university else "",
            "is_active": u.is_active,
            "is_banned": not u.is_active,
            "is_premium": u.is_premium,
            "is_verified": getattr(u, "email_verified", False),
            "superlike_balance": u.superlike_balance,
            "created_at": u.created_at.strftime("%d.%m.%Y") if u.created_at else "",
        })
    return {"status": "ok", "users": found}


class AdminUserActionRequest(BaseModel):
    action: str  # toggle_ban, grant_premium, grant_verified, add_superlikes


@router.post("/api/webapp/admin/users/{user_id}/action")
async def webapp_admin_user_action(
    user_id: int,
    payload: AdminUserActionRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Быстрые административные действия над пользователем."""
    target = await get_user(db, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    action = payload.action.lower()
    msg = "Действие выполнено"

    if action == "toggle_ban":
        if target.id == settings.SUPERADMIN_ID:
            raise HTTPException(status_code=400, detail="Нельзя заблокировать главного администратора")
        target.is_active = not target.is_active
        msg = "Пользователь заблокирован" if not target.is_active else "Пользователь разблокирован"

    elif action == "grant_premium":
        target.is_premium = not target.is_premium
        if target.is_premium:
            target.premium_until = datetime.now(timezone.utc) + timedelta(days=365)
        msg = "Премиум активирован" if target.is_premium else "Премиум отключен"

    elif action == "grant_verified":
        target.email_verified = not target.email_verified
        msg = "Статус студента верифицирован" if target.email_verified else "Верификация снята"

    elif action == "add_superlikes":
        target.superlike_balance = (target.superlike_balance or 0) + 10
        msg = f"Начислено +10 суперлайков. Баланс: {target.superlike_balance}"

    await db.commit()
    return {
        "status": "ok",
        "message": msg,
        "user": {
            "id": target.id,
            "is_active": target.is_active,
            "is_premium": target.is_premium,
            "is_verified": target.email_verified,
            "superlike_balance": target.superlike_balance,
        }
    }


@router.get("/api/webapp/admin/reports")
async def webapp_admin_get_reports(
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Список активных жалоб для модерации."""
    res = await db.execute(
        select(Report)
        .options(
            selectinload(Report.reporter).selectinload(User.profile),
            selectinload(Report.reported).selectinload(User.profile),
        )
        .where(Report.status == ReportStatus.pending)
        .order_by(Report.created_at.desc())
        .limit(20)
    )
    reports = res.scalars().all()

    items = []
    for r in reports:
        reporter_p = r.reporter.profile if (r.reporter and r.reporter.profile) else None
        reported_p = r.reported.profile if (r.reported and r.reported.profile) else None

        items.append({
            "id": str(r.id),
            "reporter_id": r.reporter_id,
            "reporter_name": reporter_p.name if reporter_p else f"ID {r.reporter_id}",
            "reported_id": r.reported_id,
            "reported_name": reported_p.name if reported_p else f"ID {r.reported_id}",
            "reason": r.reason,
            "created_at": r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "",
        })
    return {"status": "ok", "reports": items}


class ResolveReportRequest(BaseModel):
    action: str  # ban_reported, dismiss


@router.post("/api/webapp/admin/reports/{report_id}/resolve")
async def webapp_admin_resolve_report(
    report_id: str,
    payload: ResolveReportRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Модерация жалобы: бан нарушителя или отклонение."""
    import uuid
    rep_uuid = uuid.UUID(report_id)
    report = await db.get(Report, rep_uuid)
    if not report:
        raise HTTPException(status_code=404, detail="Жалоба не найдена")

    if payload.action == "ban_reported":
        reported_user = await get_user(db, report.reported_id)
        if reported_user and reported_user.id != settings.SUPERADMIN_ID:
            reported_user.is_active = False
        report.status = ReportStatus.resolved
        report.resolution_note = f"Заблокирован супер-админом {admin.id}"
    else:
        report.status = ReportStatus.dismissed
        report.resolution_note = "Отклонено администратором"

    report.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok"}





# ─── Медиа-прокси: отдача фото из Telegram Bot API ───────────
@router.get("/api/webapp/photo/{file_id:path}")
async def webapp_photo_proxy(file_id: str):
    """
    Безопасный медиа-прокси с дисковым кэшированием:
    - Отдает из локального кэша за 1-2 мс
    - Если нет в кэше, запрашивает Telegram Bot API и сохраняет
    - При любой ошибке возвращает DEFAULT_FALLBACK_AVATAR вместо поломанного 404/500
    """
    if not file_id or file_id.strip().lower() in ("none", "null", "undefined", ""):
        return RedirectResponse(DEFAULT_FALLBACK_AVATAR, status_code=307)

    # 1. Если передана внешняя ссылка (http/https)
    if file_id.startswith("http://") or file_id.startswith("https://"):
        return RedirectResponse(file_id, status_code=307)

    # 2. Если передан локальный путь на сервере
    if file_id.startswith("static/") or file_id.startswith("uploads/") or file_id.startswith("web/"):
        clean_p = file_id.lstrip("/web/").lstrip("/")
        if not clean_p.startswith("web/"):
            clean_p = os.path.join("web", clean_p)
        if os.path.exists(clean_p):
            return FileResponse(clean_p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})

    file_hash = hashlib.md5(file_id.encode("utf-8")).hexdigest()
    cached_file = os.path.join(PHOTO_CACHE_DIR, f"{file_hash}.jpg")

    # 3. Если файл уже сохранён на диске — отдаем мгновенно из локального хранилища
    if os.path.exists(cached_file) and os.path.getsize(cached_file) > 0:
        return FileResponse(
            cached_file,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=604800"}  # 7 дней в браузере
        )

    # 4. Запрашиваем файл у Telegram Bot API
    get_file_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getFile?file_id={file_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(get_file_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.warning(f"Telegram getFile returned HTTP {resp.status} for file_id {file_id}")
                    return RedirectResponse(DEFAULT_FALLBACK_AVATAR, status_code=307)
                data = await resp.json()
                if not data.get("ok") or not data.get("result", {}).get("file_path"):
                    logger.warning(f"Telegram getFile data not ok for file_id {file_id}: {data}")
                    return RedirectResponse(DEFAULT_FALLBACK_AVATAR, status_code=307)
                tg_file_path = data["result"]["file_path"]

            # 5. Скачиваем бинарные данные картинки
            download_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{tg_file_path}"
            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=8)) as img_resp:
                if img_resp.status != 200:
                    logger.warning(f"Telegram file download failed HTTP {img_resp.status}")
                    return RedirectResponse(DEFAULT_FALLBACK_AVATAR, status_code=307)
                content = await img_resp.read()
                content_type = img_resp.headers.get("Content-Type", "image/jpeg")

                # Сохраняем в дисковый кэш
                try:
                    with open(cached_file, "wb") as f:
                        f.write(content)
                except Exception as save_err:
                    logger.warning(f"Failed to write cache file {cached_file}: {save_err}")

                return Response(
                    content=content,
                    media_type=content_type,
                    headers={"Cache-Control": "public, max-age=604800"}
                )
    except Exception as e:
        logger.warning(f"Error proxying telegram image {file_id}: {e}")
        return RedirectResponse(DEFAULT_FALLBACK_AVATAR, status_code=307)
