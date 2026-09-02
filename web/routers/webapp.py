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

import aiohttp
from fastapi import APIRouter, Request, Depends, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import selectinload

from bot.config import settings
from web.dependencies import get_db, SECRET, ALGORITHM
import jwt
from database.models import (
    User, Profile, University, Swipe, Match, SwipeAction, ModeEnum, InterestTag
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


# ─── Валидация Telegram WebApp initData ──────────────────────
def verify_telegram_init_data(init_data: str, bot_token: str) -> Optional[Dict[str, Any]]:
    """
    Криптографическая проверка подписи initData от Telegram WebApp (HMAC-SHA256).
    Возвращает dict с данными пользователя или None при невалидной подписи.
    """
    if not init_data:
        return None
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            return None
        received_hash = parsed_data.pop("hash")

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )

        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
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
@router.get("/app", response_class=HTMLResponse)
@router.get("/webapp", response_class=HTMLResponse)
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
        cand_profile = await get_next_profile(db, viewer_id=student.id, mode=mode)
        if not cand_profile or cand_profile.user_id in seen_ids:
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

        # Преобразуем фото в URL медиа-прокси
        photo_urls = [f"/api/webapp/photo/{pid}" for pid in photos if pid]

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
            "career_portfolio_url": p.career_portfolio_url if mode == ModeEnum.career else None,
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
            p_name = p_profile.name if (p_profile and p_profile.name) else "Студент"
            p_photos = list(p_profile.photos) if (p_profile and p_profile.photos) else []
            match_data = {
                "user_id": partner.id,
                "name": p_name,
                "tg_username": partner.tg_username,
                "photo_url": f"/api/webapp/photo/{p_photos[0]}" if p_photos else None,
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
        photo_url = f"/api/webapp/photo/{photos[0]}" if photos else None

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
            likes_list.append({
                "user_id": c.id,
                "name": p.name if (p and p.name) else "Студент",
                "age": p.age if p else None,
                "year": p.year if p else None,
                "university": c.university.short_name if c.university else "",
                "photo_url": f"/api/webapp/photo/{photos[0]}" if photos else None,
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
    photo_urls = [f"/api/webapp/photo/{pid}" for pid in photos if pid]

    tags = []
    if p and p.interest_ids:
        tag_res = await db.execute(select(InterestTag).where(InterestTag.id.in_(p.interest_ids)))
        for t in tag_res.scalars().all():
            tags.append({"id": t.id, "name": t.name, "emoji": t.emoji})

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


# ─── Медиа-прокси: отдача фото из Telegram Bot API ───────────
# Кэш file_path в памяти: file_id -> (file_path, expire_time)
_file_path_cache: Dict[str, str] = {}


@router.get("/api/webapp/photo/{file_id}")
async def webapp_photo_proxy(file_id: str):
    """
    Безопасный медиа-прокси: получает фото из Telegram Bot API по file_id
    и отдает его браузеру с кэшированием без раскрытия BOT_TOKEN.
    """
    if not file_id or file_id in ("none", "null", "undefined"):
        raise HTTPException(status_code=404, detail="File not found")

    file_path = _file_path_cache.get(file_id)

    # 1. Получаем путь к файлу у Telegram Bot API
    if not file_path:
        get_file_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getFile?file_id={file_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(get_file_url, timeout=5) as resp:
                    if resp.status != 200:
                        raise HTTPException(status_code=404, detail="Photo not found in Telegram")
                    data = await resp.json()
                    if not data.get("ok"):
                        raise HTTPException(status_code=404, detail="Telegram getFile returned error")
                    file_path = data["result"]["file_path"]
                    _file_path_cache[file_id] = file_path
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Error resolving telegram file_id {file_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch image from Telegram")

    # 2. Стримим бинарные данные картинки
    download_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url, timeout=10) as img_resp:
                if img_resp.status != 200:
                    raise HTTPException(status_code=404, detail="Failed to download image")
                content = await img_resp.read()
                content_type = img_resp.headers.get("Content-Type", "image/jpeg")
                return Response(
                    content=content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # Кэшировать на 24 часа
                    }
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Error streaming telegram image: {e}")
        raise HTTPException(status_code=500, detail="Image streaming error")
