"""
Роутер Telegram Mini App (WebApp) для StudMatch.
Полнофункциональный SPA: авторизация через initData, свайпы, мэтчи, профиль, медиа-прокси.
"""
import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Set, Tuple, Union
from urllib.parse import parse_qsl

import os
import aiohttp
from fastapi import APIRouter, Request, Depends, HTTPException, Header, Response, Query, WebSocket, WebSocketDisconnect, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import selectinload

import html
import uuid

from bot.config import settings
from database.session import AsyncSessionLocal
from web.dependencies import get_db, SECRET, ALGORITHM
import jwt
from database.models import (
    User, Profile, University, Swipe, Match, ChatMessage, SwipeAction, ModeEnum, InterestTag,
    Report, ReportStatus, UserPrivacy, SupportTicket, TicketStatus, Project,
)
from database.crud import (
    get_user, get_profile, get_or_create_profile, get_next_profile, create_swipe,
    get_user_matches, get_incoming_likes, get_incoming_likes_count,
    deduct_superlike, get_match_by_id, get_chat_messages, create_chat_message,
    mark_chat_messages_as_read, get_unread_messages_count, get_last_chat_message,
    approve_match_telegram, delete_match_by_id, get_match_between_users,
    transfer_superlike_rating, update_user_last_active,
    get_or_create_user_privacy, update_user_privacy, toggle_photo_privacy,
    is_user_online_visible_to, get_user_online_status_text_for,
    create_project, get_project, get_user_projects, update_project, delete_project,
    get_projects_feed, get_project_candidates, founder_swipe_candidate,
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
    await update_user_last_active(db, user.id)
    return user


# ─── HTML Страница WebApp ─────────────────────────────────────
@router.get("/app", response_class=HTMLResponse)
async def webapp_page(request: Request):
    """Отдача основного HTML5 SPA приложения для Telegram WebApp."""
    from bot.utils.dynamic_settings import get_system_setting

    mm_val = await get_system_setting("maintenance_mode", "false")
    is_maintenance = mm_val.lower() in ("true", "1", "yes", "on")
    default_msg = "Некоторые функции могут быть временно недоступны на время обновления. Спасибо за понимание! ❤️"
    maintenance_message = await get_system_setting("maintenance_message", default_msg)
    if not maintenance_message or not maintenance_message.strip():
        maintenance_message = default_msg

    # Автоматический cache-busting по времени изменения (mtime) файлов статики
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "webapp")
    try:
        js_v = str(int(os.path.getmtime(os.path.join(static_dir, "webapp.js"))))
    except Exception:
        js_v = "20260913_2125"
    try:
        css_v = str(int(os.path.getmtime(os.path.join(static_dir, "webapp.css"))))
    except Exception:
        css_v = "20260913_2125"

    return templates.TemplateResponse(
        "webapp.html",
        {
            "request": request,
            "bot_username": settings.BOT_USERNAME,
            "is_maintenance": is_maintenance,
            "maintenance_message": maintenance_message,
            "js_version": js_v,
            "css_version": css_v,
        }
    )


@router.get("/webapp", response_class=HTMLResponse, include_in_schema=False)
async def webapp_page_alias(request: Request):
    """Алиас маршрута /app для обратной совместимости."""
    return await webapp_page(request)


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

    # Мок только в явном DEBUG-режиме (не в production — BOT_TOKEN.startswith("test_") убран)
    if not tg_user and _DEBUG and payload.init_data == "dev_mock":
        tg_user = {"id": 100001, "username": "test_student", "first_name": "Тестовый"}

    if not tg_user:
        raise HTTPException(status_code=403, detail="Неверная подпись Telegram initData")

    user_id = int(tg_user["id"])
    tg_username = tg_user.get("username")

    from database.crud import get_or_create_user
    user = await get_or_create_user(db, user_id=user_id, tg_username=tg_username)

    now = datetime.now(timezone.utc)
    # Промо-акция: 2 месяца (60 дней) бесплатного Премиума всем новым пользователям до 10 октября 2026
    promo_until = datetime(2026, 10, 10, 23, 59, 59, tzinfo=timezone.utc)
    if now <= promo_until and not user.premium_until:
        user.premium_until = now + timedelta(days=60)
        user.superlike_balance = max(user.superlike_balance or 0, 5)
        await db.commit()

    is_superadmin = (user.id == settings.SUPERADMIN_ID or user.id in settings.admin_ids)
    if is_superadmin:
        if not user.premium_until:
            user.premium_until = now + timedelta(days=365)
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
    photo_urls = []
    if profile:
        if user.mode == ModeEnum.career and profile.career_avatar_file_id:
            c_photos = [profile.career_avatar_file_id]
        else:
            c_photos = list(profile.photos) if profile.photos else ([profile.avatar_file_id] if profile.avatar_file_id else [])
        photo_urls = [resolve_photo_url(pid) for pid in c_photos if resolve_photo_url(pid)]

    from bot.utils.dynamic_settings import get_system_setting
    mm_val = await get_system_setting("maintenance_mode", "false")
    is_maintenance = mm_val.lower() in ("true", "1", "yes", "on")
    default_msg = "Некоторые функции могут быть временно недоступны на время обновления. Спасибо за понимание! ❤️"
    maintenance_message = await get_system_setting("maintenance_message", default_msg)
    if not maintenance_message or not maintenance_message.strip():
        maintenance_message = default_msg

    return {
        "status": "ok",
        "token": token,
        "maintenance": {
            "is_active": is_maintenance,
            "message": maintenance_message,
        },
        "user": {
            "id": user.id,
            "name": profile.name if profile else "Студент",
            "username": user.tg_username,
            "photos": photo_urls,
            "avatar_url": photo_urls[0] if photo_urls else DEFAULT_FALLBACK_AVATAR,
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
        if mode == ModeEnum.career:
            if p.career_avatar_file_id:
                photos = [p.career_avatar_file_id]
            else:
                photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])
        else:
            photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])

        # Проверяем настройки приватности кандидата
        cand_privacy = u.privacy if (u and "privacy" in u.__dict__) else None
        if not cand_privacy and u:
            cand_privacy = await get_or_create_user_privacy(db, u.id)

        hide_age = getattr(cand_privacy, "hide_age", False) if cand_privacy else False
        hide_course = getattr(cand_privacy, "hide_course", False) if cand_privacy else False
        priv_photos_set = set(cand_privacy.private_photos or []) if cand_privacy else set()

        # Формируем фотографии и метаданные с пометкой блюра (is_private)
        photos_meta = []
        for idx, pid in enumerate(photos):
            url = resolve_photo_url(pid)
            if not url:
                continue
            # Первое фото (idx == 0) ВСЕГДА открыто
            # Дополнительные фото (idx > 0) приватны, если они в private_photos
            is_priv = bool(idx > 0 and str(pid).strip() in priv_photos_set)
            photos_meta.append({
                "id": str(pid),
                "url": url,
                "is_private": is_priv,
            })

        if not photos_meta:
            photos_meta = [{"id": "fallback", "url": DEFAULT_FALLBACK_AVATAR, "is_private": False}]

        photo_urls = [pm["url"] for pm in photos_meta]

        cand_tags = [tags_map[tid] for tid in (p.interest_ids or []) if tid in tags_map]
        univ_name = u.university.short_name if (u and u.university) else ""

        result.append({
            "user_id": p.user_id,
            "name": p.name or "Студент",
            "age": None if hide_age else p.age,
            "year": None if hide_course else p.year,
            "hide_age": hide_age,
            "hide_course": hide_course,
            "major": p.major or "",
            "university": univ_name,
            "goal": p.goal or "",
            "custom_interests": p.custom_interests or "",
            "tags": cand_tags,
            "photos": photo_urls,
            "photos_meta": photos_meta,
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

    # Заранее сохраняем необходимые скалярные атрибуты до любых операций с БД во избежание MissingGreenlet
    current_superlike_balance = int(getattr(student, "superlike_balance", 0) or 0)
    user_mode = getattr(student, "mode", ModeEnum.dating) or ModeEnum.dating
    student_id = student.id

    # Проверка баланса суперлайков
    if action == SwipeAction.superlike:
        if current_superlike_balance <= 0:
            raise HTTPException(status_code=400, detail="Недостаточно суперлайков на балансе")
        deducted = await deduct_superlike(db, student_id)
        if not deducted:
            raise HTTPException(status_code=400, detail="Недостаточно суперлайков")
        current_superlike_balance = max(0, current_superlike_balance - 1)

    swipe_comment = payload.comment
    if swipe_comment and swipe_comment.strip():
        target_privacy = await get_or_create_user_privacy(db, payload.target_id)
        msg_perm = target_privacy.message_permission or "matches"
        if msg_perm == "nobody" or (msg_perm == "verified_only" and not getattr(student, "email_verified", False)):
            swipe_comment = None

    is_match = await create_swipe(
        db,
        from_id=student_id,
        to_id=payload.target_id,
        action=action,
        mode=user_mode,
        comment=swipe_comment,
    )

    match_data = None
    if is_match:
        partner = await get_user(db, payload.target_id)
        if partner:
            p_profile = partner.profile
            p_name = p_profile.name if (p_profile and p_profile.name) else "Студент"
            if user_mode == ModeEnum.career and p_profile and p_profile.career_avatar_file_id:
                first_p = p_profile.career_avatar_file_id
            else:
                p_photos = list(p_profile.photos) if (p_profile and p_profile.photos) else ([p_profile.avatar_file_id] if (p_profile and p_profile.avatar_file_id) else [])
                first_p = p_photos[0] if p_photos else None

            p_photo_url = resolve_photo_url(first_p) or DEFAULT_FALLBACK_AVATAR
            match_obj = await get_match_between_users(db, student_id, partner.id, user_mode)
            match_id_str = str(match_obj.id) if match_obj else ""

            match_data = {
                "match_id": match_id_str,
                "user_id": partner.id,
                "name": p_name,
                "tg_username": None,  # Скрыто до обоюдного согласия
                "is_tg_unlocked": False,
                "photo_url": p_photo_url,
                "photos": [p_photo_url],
            }

            # Отправка Telegram-уведомления партнеру в фоновом режиме без раскрытия Telegram
            try:
                from aiogram import Bot
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
                bot = Bot(token=settings.BOT_TOKEN)
                my_prof = await get_profile(db, student_id)
                student_name = my_prof.name if (my_prof and my_prof.name) else "Студент"
                chat_url = f"{settings.webapp_url}?startapp=chat_{match_id_str}" if match_id_str else settings.webapp_url
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="💬 Открыть чат в приложении", web_app=WebAppInfo(url=chat_url))
                ]])
                await bot.send_message(
                    chat_id=partner.id,
                    text=(
                        f"🎉 <b>Это взаимно!</b>\n\n"
                        f"Ты и <b>{html.escape(student_name)}</b> понравились друг другу!\n\n"
                        f"Начните общение во внутреннем чате приложения 💬"
                    ),
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                await bot.session.close()
            except Exception as e:
                logger.warning(f"Failed to notify match partner via bot: {e}")

    return {
        "status": "ok",
        "action": action.value,
        "is_match": is_match,
        "match": match_data,
        "superlike_balance": current_superlike_balance,
    }


# ─── API: Список мэтчей и диалогов (Matches & Chats) ─────────
class ChatSendMessageRequest(BaseModel):
    text: str


class ChatReportRequest(BaseModel):
    reason: str
    details: Optional[str] = ""


class ChatConnectionManager:
    def __init__(self):
        # match_id (str) -> dict of (user_id -> set of WebSockets)
        self.active_rooms: Dict[str, Dict[int, Set[WebSocket]]] = {}

    async def connect(self, websocket: WebSocket, match_id: str, user_id: int):
        await websocket.accept()
        if match_id not in self.active_rooms:
            self.active_rooms[match_id] = {}
        if user_id not in self.active_rooms[match_id]:
            self.active_rooms[match_id][user_id] = set()
        self.active_rooms[match_id][user_id].add(websocket)

    def disconnect(self, websocket: WebSocket, match_id: str, user_id: int):
        if match_id in self.active_rooms:
            if user_id in self.active_rooms[match_id]:
                self.active_rooms[match_id][user_id].discard(websocket)
                if not self.active_rooms[match_id][user_id]:
                    del self.active_rooms[match_id][user_id]
            if not self.active_rooms[match_id]:
                del self.active_rooms[match_id]

    def is_user_in_chat(self, match_id: str, user_id: int) -> bool:
        """Проверяет, держит ли пользователь данный чат открытым."""
        return bool(self.active_rooms.get(match_id, {}).get(user_id))

    async def broadcast_to_match(self, match_id: str, message: dict):
        """Отправляет событие всем подключенным участникам диалога."""
        room = self.active_rooms.get(match_id, {})
        dead_conns = []
        for uid, ws_set in list(room.items()):
            for ws in list(ws_set):
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_conns.append((uid, ws))
        for uid, ws in dead_conns:
            self.disconnect(ws, match_id, uid)


chat_manager = ChatConnectionManager()

# Кэш времени последнего Telegram-уведомления: (match_id, recipient_id) -> timestamp
_chat_notify_timestamps: Dict[str, float] = {}


async def notify_partner_about_message(
    recipient_id: int, sender_name: str, message_text: str, match_id: str
):
    import time
    now = time.time()
    cache_key = f"{match_id}:{recipient_id}"
    last_notified = _chat_notify_timestamps.get(cache_key, 0)

    # Троттлинг: не чаще 1 раза в 120 секунд
    if now - last_notified < 120:
        return

    _chat_notify_timestamps[cache_key] = now

    try:
        from aiogram import Bot
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        bot = Bot(token=settings.BOT_TOKEN)
        clean_name = html.escape(sender_name or "Студент")
        preview = message_text[:60] + ("…" if len(message_text) > 60 else "")
        clean_preview = html.escape(preview)
        chat_url = f"{settings.webapp_url}?startapp=chat_{match_id}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✉️ Ответить в чате", web_app=WebAppInfo(url=chat_url))
        ]])
        await bot.send_message(
            chat_id=recipient_id,
            text=(
                f"💬 <b>Новое сообщение от {clean_name}:</b>\n\n"
                f"<i>«{clean_preview}»</i>"
            ),
            parse_mode="HTML",
            reply_markup=kb,
        )
        await bot.session.close()
    except Exception as e:
        logger.warning(f"Failed to send chat bot notification to {recipient_id}: {e}")


@router.get("/api/webapp/matches")
async def webapp_matches(
    mode: Optional[str] = None,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Список взаимных мэтчей и диалогов студента, отфильтрованных по режиму."""
    req_mode_str = mode
    if not req_mode_str:
        if hasattr(student, "mode") and student.mode:
            req_mode_str = student.mode.value if hasattr(student.mode, "value") else str(student.mode)
        else:
            req_mode_str = "dating"

    mode_enum = None
    if req_mode_str == "career":
        mode_enum = ModeEnum.career
    elif req_mode_str == "projects":
        mode_enum = ModeEnum.projects
    elif req_mode_str == "dating":
        mode_enum = ModeEnum.dating

    matches = await get_user_matches(db, student.id, mode=mode_enum)
    result = []

    for m, partner in matches:
        p = partner.profile
        raw_name = p.name if (p and p.name) else "Студент"
        photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
        first_p = photos[0] if photos else None
        photo_url = resolve_photo_url(first_p) or DEFAULT_FALLBACK_AVATAR

        univ_name = partner.university.short_name if partner.university else ""
        date_str = m.created_at.strftime("%d.%m") if m.created_at else ""

        is_tg_unlocked = bool(m.user1_tg_approved and m.user2_tg_approved)
        my_tg_approved = bool(m.user1_tg_approved if m.user1_id == student.id else m.user2_tg_approved)
        partner_tg_approved = bool(m.user2_tg_approved if m.user1_id == student.id else m.user1_tg_approved)

        last_msg = await get_last_chat_message(db, m.id)
        unread_count = await get_unread_messages_count(db, m.id, student.id)

        last_msg_data = None
        if last_msg:
            last_msg_data = {
                "id": str(last_msg.id),
                "sender_id": last_msg.sender_id,
                "text": last_msg.text,
                "msg_type": last_msg.msg_type,
                "is_read": last_msg.is_read,
                "created_at": last_msg.created_at.strftime("%H:%M") if last_msg.created_at else "",
                "timestamp": last_msg.created_at.timestamp() if last_msg.created_at else 0,
            }

        partner_privacy = partner.privacy if (partner and "privacy" in partner.__dict__) else None
        if not partner_privacy and partner:
            partner_privacy = await get_or_create_user_privacy(db, partner.id)

        hide_age = getattr(partner_privacy, "hide_age", False)
        hide_course = getattr(partner_privacy, "hide_course", False)

        result.append({
            "match_id": str(m.id),
            "user_id": partner.id,
            "mode": m.mode.value if hasattr(m.mode, "value") else str(m.mode),
            "project_id": str(m.project_id) if m.project_id else None,
            "project_title": m.project.title if (m.project and m.project.title) else None,
            "name": raw_name,
            # ПРЯМОЙ TELEGRAM ДОСТУПЕН ТОЛЬКО ПОСЛЕ ОБОЮДНОГО СОГЛАСИЯ!
            "tg_username": partner.tg_username if is_tg_unlocked else None,
            "is_tg_unlocked": is_tg_unlocked,
            "my_tg_approved": my_tg_approved,
            "partner_tg_approved": partner_tg_approved,
            "photo_url": photo_url,
            "year": None if hide_course else (p.year if p else None),
            "age": None if hide_age else (p.age if p else None),
            "hide_age": hide_age,
            "hide_course": hide_course,
            "major": p.major if p else None,
            "university": univ_name,
            "goal": p.goal if p else None,
            "created_at": date_str,
            "is_verified": getattr(partner, "email_verified", False),
            "is_premium": getattr(partner, "is_premium", False),
            "is_online": is_user_online_visible_to(student.id, partner, is_mutual_match=True),
            "online_status_text": get_user_online_status_text_for(student.id, partner, is_mutual_match=True),
            "unread_count": unread_count,
            "last_message": last_msg_data,
            "_sort_time": last_msg_data["timestamp"] if last_msg_data else (m.created_at.timestamp() if m.created_at else 0),
        })

    # Сортируем: сначала диалоги с самыми свежими сообщениями
    result.sort(key=lambda x: x["_sort_time"], reverse=True)
    for r in result:
        r.pop("_sort_time", None)

    return {"status": "ok", "count": len(result), "matches": result}


@router.get("/api/webapp/matches/{match_id}/messages")
async def webapp_get_match_messages(
    match_id: str,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """История сообщений диалога с автоматической пометкой прочтения."""
    match = None
    match_uuid = None
    try:
        match_uuid = uuid.UUID(match_id)
        match = await get_match_by_id(db, match_uuid)
    except Exception:
        pass

    if not match:
        try:
            partner_user_id = int(match_id)
            cur_mode = student.mode if hasattr(student, "mode") else None
            match = await get_match_between_users(db, student.id, partner_user_id, mode=cur_mode)
            if not match:
                match = await get_match_between_users(db, student.id, partner_user_id)
            if match:
                match_uuid = match.id
        except Exception:
            pass

    if not match:
        raise HTTPException(status_code=404, detail="Мэтч не найден")
    if student.id not in (match.user1_id, match.user2_id):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    partner_id = match.user2_id if match.user1_id == student.id else match.user1_id
    partner = await get_user(db, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Собеседник не найден")

    # Помечаем сообщения как прочитанные
    read_count = await mark_chat_messages_as_read(db, match_uuid, student.id)
    if read_count > 0:
        await chat_manager.broadcast_to_match(str(match_uuid), {
            "type": "read",
            "reader_id": student.id,
        })

    msgs = await get_chat_messages(db, match_uuid, limit=100)
    messages_data = []
    for msg in msgs:
        messages_data.append({
            "id": str(msg.id),
            "sender_id": msg.sender_id,
            "is_mine": bool(msg.sender_id == student.id),
            "text": msg.text,
            "msg_type": msg.msg_type,
            "is_read": msg.is_read,
            "created_at": msg.created_at.strftime("%H:%M") if msg.created_at else "",
            "date": msg.created_at.strftime("%d.%m.%Y") if msg.created_at else "",
        })

    p = partner.profile
    photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
    first_p = photos[0] if photos else None
    photo_url = resolve_photo_url(first_p) or DEFAULT_FALLBACK_AVATAR

    is_tg_unlocked = bool(match.user1_tg_approved and match.user2_tg_approved)
    my_tg_approved = bool(match.user1_tg_approved if match.user1_id == student.id else match.user2_tg_approved)
    partner_tg_approved = bool(match.user2_tg_approved if match.user1_id == student.id else match.user1_tg_approved)

    partner_tg = partner.tg_username if is_tg_unlocked else None

    partner_privacy = partner.privacy if (partner and "privacy" in partner.__dict__) else None
    if not partner_privacy and partner:
        partner_privacy = await get_or_create_user_privacy(db, partner.id)

    hide_age = getattr(partner_privacy, "hide_age", False)
    hide_course = getattr(partner_privacy, "hide_course", False)
    msg_perm = partner_privacy.message_permission or "matches"
    can_send_message = True
    message_block_reason = ""
    if msg_perm == "nobody":
        can_send_message = False
        message_block_reason = "Пользователь ограничил входящие сообщения 🔒"
    elif msg_perm == "verified_only" and not getattr(student, "email_verified", False):
        can_send_message = False
        message_block_reason = "Сообщения разрешены только верифицированным студентам 🎓"

    partner_dict = {
        "id": partner.id,
        "name": p.name if (p and p.name) else "Студент",
        "photo_url": photo_url,
        "avatar_url": photo_url,
        "university": partner.university.short_name if partner.university else "",
        "year": None if hide_course else (p.year if p else None),
        "age": None if hide_age else (p.age if p else None),
        "hide_age": hide_age,
        "hide_course": hide_course,
        "is_verified": getattr(partner, "email_verified", False),
        "is_premium": getattr(partner, "is_premium", False),
        "is_online": is_user_online_visible_to(student.id, partner, is_mutual_match=True),
        "online_status_text": get_user_online_status_text_for(student.id, partner, is_mutual_match=True),
        # Скрыт до обоюдного согласия!
        "tg_username": partner_tg,
        "can_send_message": can_send_message,
        "message_block_reason": message_block_reason,
    }

    match_dict = {
        "id": str(match.id),
        "match_id": str(match.id),
        "partner": partner_dict,
        "is_tg_unlocked": is_tg_unlocked,
        "my_tg_approved": my_tg_approved,
        "partner_tg_approved": partner_tg_approved,
        "partner_tg_username": partner_tg,
        "can_send_message": can_send_message,
        "message_block_reason": message_block_reason,
    }

    return {
        "status": "ok",
        "match": match_dict,
        "match_id": str(match.id),
        "partner": partner_dict,
        "is_tg_unlocked": is_tg_unlocked,
        "my_tg_approved": my_tg_approved,
        "partner_tg_approved": partner_tg_approved,
        "partner_tg_username": partner_tg,
        "can_send_message": can_send_message,
        "message_block_reason": message_block_reason,
        "messages": messages_data,
    }



@router.post("/api/webapp/matches/{match_id}/messages")
async def webapp_send_message(
    match_id: str,
    payload: ChatSendMessageRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Отправка текстового сообщения во внутренний чат."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    match = None
    match_uuid = None
    try:
        match_uuid = uuid.UUID(match_id)
        match = await get_match_by_id(db, match_uuid)
    except Exception:
        pass

    if not match:
        try:
            partner_user_id = int(match_id)
            cur_mode = student.mode if hasattr(student, "mode") else None
            match = await get_match_between_users(db, student.id, partner_user_id, mode=cur_mode)
            if not match:
                match = await get_match_between_users(db, student.id, partner_user_id)
            if match:
                match_uuid = match.id
        except Exception:
            pass

    if not match:
        raise HTTPException(status_code=404, detail="Мэтч не найден")
    if student.id not in (match.user1_id, match.user2_id):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    partner_id = match.user2_id if match.user1_id == student.id else match.user1_id
    partner_privacy = await get_or_create_user_privacy(db, partner_id)
    msg_perm = partner_privacy.message_permission or "matches"
    if msg_perm == "nobody":
        raise HTTPException(status_code=403, detail="Пользователь ограничил входящие сообщения 🔒")
    if msg_perm == "verified_only" and not getattr(student, "email_verified", False):
        raise HTTPException(status_code=403, detail="Сообщения разрешены только верифицированным студентам 🎓")

    msg = await create_chat_message(db, match_uuid, student.id, text, msg_type="text")

    # Транслируем новое сообщение через WebSocket
    msg_data = {
        "id": str(msg.id),
        "sender_id": msg.sender_id,
        "text": msg.text,
        "msg_type": msg.msg_type,
        "is_read": False,
        "created_at": msg.created_at.strftime("%H:%M") if msg.created_at else "",
        "date": msg.created_at.strftime("%d.%m.%Y") if msg.created_at else "",
    }

    await chat_manager.broadcast_to_match(str(match_uuid), {
        "type": "new_message",
        "message": msg_data,
    })

    # Если получатель не держит данный чат открытым в WebApp прямо сейчас — отправляем уведомление через бота
    if not chat_manager.is_user_in_chat(str(match_uuid), partner_id):
        my_name = student.profile.name if (student.profile and student.profile.name) else "Собеседник"
        await notify_partner_about_message(partner_id, my_name, text, str(match_uuid))

    return {
        "status": "ok",
        "message": msg_data,
    }


@router.post("/api/webapp/matches/{match_id}/request_telegram")
async def webapp_request_telegram(
    match_id: str,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Пользователь выражает согласие на открытие своего Telegram."""
    try:
        match_uuid = uuid.UUID(match_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный ID матча")

    match = await get_match_by_id(db, match_uuid)
    if not match:
        raise HTTPException(status_code=404, detail="Мэтч не найден")
    if student.id not in (match.user1_id, match.user2_id):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    partner_id = match.user2_id if match.user1_id == student.id else match.user1_id
    partner = await get_user(db, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Собеседник не найден")

    updated_match, is_now_unlocked = await approve_match_telegram(db, match_uuid, student.id)
    if not updated_match:
        raise HTTPException(status_code=400, detail="Не удалось обновить статус")

    student_name = student.profile.name if (student.profile and student.profile.name) else "Собеседник"
    partner_name = partner.profile.name if (partner and partner.profile and partner.profile.name) else "Собеседник"

    if is_now_unlocked:
        sys_msg = await create_chat_message(
            db, match_uuid, student.id,
            "🎉 Взаимное согласие получено! Теперь вы можете перейти в Telegram.",
            msg_type="tg_approved",
        )
        # Уведомляем обоих участников через бота о разблокировке Telegram!
        try:
            from aiogram import Bot
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            bot = Bot(token=settings.BOT_TOKEN)

            # Уведомляем собеседника
            if student.tg_username:
                clean_my_tg = student.tg_username.lstrip("@")
                kb_partner = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="💬 Написать в Telegram", url=f"https://t.me/{clean_my_tg}")
                ]])
                await bot.send_message(
                    chat_id=partner.id,
                    text=(
                        f"🎉 <b>Взаимное согласие получено!</b>\n\n"
                        f"Вы с <b>{html.escape(student_name)}</b> открыли контакты в Telegram!\n"
                        f"Telegram: <b>@{clean_my_tg}</b>"
                    ),
                    parse_mode="HTML",
                    reply_markup=kb_partner,
                )

            # Уведомляем инициатора
            if partner.tg_username:
                clean_partner_tg = partner.tg_username.lstrip("@")
                kb_me = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="💬 Написать в Telegram", url=f"https://t.me/{clean_partner_tg}")
                ]])
                await bot.send_message(
                    chat_id=student.id,
                    text=(
                        f"🎉 <b>Взаимное согласие получено!</b>\n\n"
                        f"Вы с <b>{html.escape(partner_name)}</b> открыли контакты в Telegram!\n"
                        f"Telegram: <b>@{clean_partner_tg}</b>"
                    ),
                    parse_mode="HTML",
                    reply_markup=kb_me,
                )
            await bot.session.close()
        except Exception as e:
            logger.warning(f"Failed to send unlock bot notifications: {e}")
    else:
        sys_msg = await create_chat_message(
            db, match_uuid, student.id,
            f"✨ {html.escape(student_name)} предлагает перейти в Telegram! Нажми кнопку выше, чтобы открыть контакты взаимно.",
            msg_type="tg_request",
        )

    # Транслируем в WebSocket
    await chat_manager.broadcast_to_match(str(match_uuid), {
        "type": "tg_approval_update",
        "is_tg_unlocked": updated_match.is_tg_unlocked,
        "user1_tg_approved": updated_match.user1_tg_approved,
        "user2_tg_approved": updated_match.user2_tg_approved,
        "system_message": {
            "id": str(sys_msg.id),
            "text": sys_msg.text,
            "msg_type": sys_msg.msg_type,
            "created_at": sys_msg.created_at.strftime("%H:%M") if sys_msg.created_at else "",
        }
    })

    my_tg_approved = updated_match.user1_tg_approved if updated_match.user1_id == student.id else updated_match.user2_tg_approved
    partner_tg_approved = updated_match.user2_tg_approved if updated_match.user1_id == student.id else updated_match.user1_tg_approved

    return {
        "status": "ok",
        "is_tg_unlocked": updated_match.is_tg_unlocked,
        "my_tg_approved": my_tg_approved,
        "partner_tg_approved": partner_tg_approved,
        "partner_tg_username": partner.tg_username if updated_match.is_tg_unlocked else None,
    }


@router.post("/api/webapp/matches/{match_id}/unmatch")
async def webapp_unmatch(
    match_id: str,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Удаление мэтча и закрытие диалога."""
    try:
        match_uuid = uuid.UUID(match_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный ID матча")

    ok = await delete_match_by_id(db, match_uuid, student.id)
    if not ok:
        raise HTTPException(status_code=400, detail="Не удалось удалить мэтч")

    await chat_manager.broadcast_to_match(str(match_uuid), {
        "type": "unmatched",
    })

    return {"status": "ok"}


@router.post("/api/webapp/matches/{match_id}/report")
async def webapp_report_from_chat(
    match_id: str,
    payload: ChatReportRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Отправка жалобы модераторам из чата с последующим удалением пары."""
    try:
        match_uuid = uuid.UUID(match_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный ID матча")

    match = await get_match_by_id(db, match_uuid)
    if not match:
        raise HTTPException(status_code=404, detail="Мэтч не найден")
    if student.id not in (match.user1_id, match.user2_id):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    partner_id = match.user2_id if match.user1_id == student.id else match.user1_id

    # Фиксируем жалобу
    report_reason = f"[Чат {match_id}] {payload.reason}"
    if payload.details:
        report_reason += f": {payload.details}"

    db.add(
        Report(
            id=uuid.uuid4(),
            reporter_id=student.id,
            reported_id=partner_id,
            reason=report_reason[:500],
            status=ReportStatus.pending,
        )
    )
    await db.commit()

    # Удаляем мэтч
    await delete_match_by_id(db, match_uuid, student.id)
    await chat_manager.broadcast_to_match(str(match_uuid), {
        "type": "unmatched",
    })

    return {"status": "ok"}


@router.websocket("/api/webapp/ws/chat/{match_id}")
async def websocket_chat_endpoint(websocket: WebSocket, match_id: str):
    """WebSocket для real-time обмена сообщениями и статусами диалога."""
    token = websocket.query_params.get("token")
    if not token:
        token = websocket.cookies.get("student_token")
    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        user_id = int(payload.get("user_id"))
    except Exception:
        await websocket.close(code=1008)
        return

    try:
        match_uuid = uuid.UUID(match_id)
    except Exception:
        await websocket.close(code=1003)
        return

    async with AsyncSessionLocal() as db:
        match = await get_match_by_id(db, match_uuid)
        if not match or user_id not in (match.user1_id, match.user2_id):
            await websocket.close(code=1008)
            return

    await chat_manager.connect(websocket, match_id, user_id)
    # Оповещаем собеседника в этой комнате о входе в сеть
    await chat_manager.broadcast_to_match(match_id, {
        "type": "user_online",
        "user_id": user_id,
    })
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif event_type == "typing":
                await chat_manager.broadcast_to_match(match_id, {
                    "type": "typing",
                    "user_id": user_id,
                })
            elif event_type == "read":
                async with AsyncSessionLocal() as db:
                    await mark_chat_messages_as_read(db, match_uuid, user_id)
                await chat_manager.broadcast_to_match(match_id, {
                    "type": "read",
                    "reader_id": user_id,
                })
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        chat_manager.disconnect(websocket, match_id, user_id)
        if not chat_manager.is_user_in_chat(match_id, user_id):
            await chat_manager.broadcast_to_match(match_id, {
                "type": "user_offline",
                "user_id": user_id,
            })


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


# ─── API: Истории (Stories / Топ пользователей с Премиумом) ─────
@router.get("/api/webapp/stories")
async def webapp_stories(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Возвращает список пользователей для верхней ленты Stories:
    1. Находит реальных пользователей с активным премиумом (premium_until > now или супер-админов).
    2. Если их меньше 10, дополняет профилями с активным бустом и высоким рейтингом.
    3. Первым элементом возвращает профиль текущего пользователя.
    """
    now = datetime.now(timezone.utc)

    # 1. В Stories попадают ТОЛЬКО пользователи с активным Премиумом
    stmt_prem = (
        select(User)
        .options(selectinload(User.profile), selectinload(User.university))
        .join(Profile, Profile.user_id == User.id)
        .where(
            and_(
                User.id != student.id,
                User.is_active.is_(True),
                User.premium_until.isnot(None),
                User.premium_until > now,
            )
        )
        .order_by(desc(User.premium_until), desc(User.created_at))
        .limit(30)
    )
    res_prem = await db.execute(stmt_prem)
    all_candidates = list(res_prem.scalars().all())

    stories = []
    for u in all_candidates:
        p = u.profile
        if not p:
            continue
        p_name = p.name or "Студент"
        first_name = p_name.split()[0] if p_name else "Студент"

        photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])
        first_photo = photos[0] if photos else None
        avatar_url = resolve_photo_url(first_photo) or DEFAULT_FALLBACK_AVATAR

        univ = (u.university.short_name or u.university.name) if u.university else (p.major or "")

        stories.append({
            "user_id": u.id,
            "name": first_name,
            "full_name": p_name,
            "avatar_url": avatar_url,
            "is_premium": bool(u.is_premium),
            "is_verified": bool(u.is_verified),
            "university": univ,
        })

    # Данные для своей истории
    my_p = student.profile
    my_photos = list(my_p.photos) if (my_p and my_p.photos) else ([my_p.avatar_file_id] if (my_p and my_p.avatar_file_id) else [])
    my_avatar = resolve_photo_url(my_photos[0] if my_photos else None) or DEFAULT_FALLBACK_AVATAR

    return {
        "status": "ok",
        "my_story": {
            "user_id": student.id,
            "name": "Моя анкета",
            "avatar_url": my_avatar,
            "is_premium": bool(student.is_premium),
        },
        "stories": stories
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

    career_avatar_url = resolve_photo_url(p.career_avatar_file_id) if (p and p.career_avatar_file_id) else None

    tags = []
    tag_ids = p.interest_ids if (p and p.interest_ids) else []
    if isinstance(tag_ids, str):
        try:
            tag_ids = json.loads(tag_ids)
        except Exception:
            tag_ids = []
    if tag_ids:
        tag_res = await db.execute(select(InterestTag).where(InterestTag.id.in_(tag_ids)))
        for t in tag_res.scalars().all():
            tags.append({"id": t.id, "name": t.name, "emoji": t.emoji})

    is_superadmin = (student.id == settings.SUPERADMIN_ID or student.id in settings.admin_ids)
    if is_superadmin:
        student.email_verified = True
        student.superlike_balance = max(student.superlike_balance or 0, 9999)
        await db.commit()

    from bot.utils.dynamic_settings import get_system_setting
    mm_val = await get_system_setting("maintenance_mode", "false")
    is_maintenance = mm_val.lower() in ("true", "1", "yes", "on")
    default_msg = "Некоторые функции могут быть временно недоступны на время обновления. Спасибо за понимание! ❤️"
    maintenance_message = await get_system_setting("maintenance_message", default_msg)
    if not maintenance_message or not maintenance_message.strip():
        maintenance_message = default_msg

    privacy = await get_or_create_user_privacy(db, student.id)
    priv_photos_set = set(privacy.private_photos or [])

    raw_photos = []
    for idx, pid in enumerate(photos):
        u_url = resolve_photo_url(pid)
        if not u_url:
            continue
        raw_photos.append({
            "id": str(pid),
            "url": u_url,
            "is_main": (idx == 0),
            "is_private": bool(idx > 0 and str(pid).strip() in priv_photos_set),
        })

    return {
        "status": "ok",
        "maintenance": {
            "is_active": is_maintenance,
            "message": maintenance_message,
        },
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
            "interest_ids": (
                json.loads(p.interest_ids) if (p and isinstance(p.interest_ids, str)) else (list(p.interest_ids) if (p and p.interest_ids) else [])
            ),
            "gender": p.gender if p else None,
            "target_gender": p.target_gender if p else "all",
            "photos": photo_urls,
            "raw_photos": raw_photos,
            "career_avatar_url": career_avatar_url,
            "career_goal": p.career_goal if p else "",
            "career_custom_skills": p.career_custom_skills if p else "",
            "career_work_format": p.career_work_format if p else "",
            "career_portfolio_url": p.career_portfolio_url if p else "",
            "career_is_complete": p.career_is_complete if p else False,
            "project_role": p.project_role if p else "",
            "project_skills": p.project_skills if p else "",
            "project_bio": p.project_bio if p else "",
            "project_is_complete": p.project_is_complete if p else False,
            "rating_score": round(p.rating_score or 0.0, 1) if p else 0.0,
            "is_superadmin": is_superadmin,
            "privacy": {
                "online_visibility": privacy.online_visibility or "all",
                "message_permission": privacy.message_permission or "matches",
                "allow_employer_access": bool(privacy.allow_employer_access),
                "hide_age": bool(privacy.hide_age),
                "hide_course": bool(privacy.hide_course),
                "hide_email": bool(privacy.hide_email),
                "private_photos": privacy.private_photos or [],
            },
        }
    }


# ─── API: Редактирование профиля студента ───────────────────
class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    year: Optional[int] = None
    major: Optional[str] = None
    goal: Optional[str] = None
    custom_interests: Optional[str] = None
    interest_ids: Optional[List[int]] = None
    gender: Optional[str] = None
    target_gender: Optional[str] = None
    career_goal: Optional[str] = None
    career_custom_skills: Optional[str] = None
    career_work_format: Optional[str] = None
    career_portfolio_url: Optional[str] = None
    project_role: Optional[str] = None
    project_skills: Optional[str] = None
    project_bio: Optional[str] = None


@router.get("/api/webapp/tags")
async def webapp_get_tags(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Список всех доступных тегов интересов."""
    res = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = [{"id": t.id, "name": t.name, "emoji": t.emoji} for t in res.scalars().all()]
    return {"status": "ok", "tags": tags}


@router.post("/api/webapp/profile")
@router.put("/api/webapp/profile")
async def webapp_update_profile(
    body: ProfileUpdateRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Обновление личных данных анкеты студента из миниаппа."""
    p = student.profile if "profile" in student.__dict__ else None
    if p is None:
        p = await get_profile(db, student.id)
    if not p:
        p = await get_or_create_profile(db, user_id=student.id)

    if body.name is not None:
        clean_name = body.name.strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="Имя не может быть пустым")
        if len(clean_name) > 100:
            raise HTTPException(status_code=400, detail="Имя слишком длинное (макс. 100 символов)")
        p.name = clean_name

    if body.age is not None:
        if body.age < 16 or body.age > 35:
            raise HTTPException(status_code=400, detail="Возраст должен быть от 16 до 35 лет")
        p.age = body.age

    if body.year is not None:
        if body.year < 1 or body.year > 6:
            raise HTTPException(status_code=400, detail="Курс должен быть от 1 до 6")
        p.year = body.year

    if body.major is not None:
        p.major = body.major.strip()[:200]

    if body.goal is not None:
        p.goal = body.goal.strip()[:2000]

    if body.custom_interests is not None:
        p.custom_interests = body.custom_interests.strip()[:500]

    if body.gender is not None:
        if body.gender in ("male", "female"):
            p.gender = body.gender

    if body.target_gender is not None:
        if body.target_gender in ("male", "female", "all"):
            p.target_gender = body.target_gender

    if body.interest_ids is not None:
        if body.interest_ids:
            res_tags = await db.execute(select(InterestTag.id).where(InterestTag.id.in_(body.interest_ids)))
            p.interest_ids = list(res_tags.scalars().all())
        else:
            p.interest_ids = []

    # Карьерная анкета
    if body.career_goal is not None:
        p.career_goal = body.career_goal.strip()[:2000]
    if body.career_custom_skills is not None:
        p.career_custom_skills = body.career_custom_skills.strip()[:500]
    if body.career_work_format is not None:
        p.career_work_format = body.career_work_format.strip()[:100]
    if body.career_portfolio_url is not None:
        p.career_portfolio_url = body.career_portfolio_url.strip()[:500]

    if p.career_goal or p.career_custom_skills:
        p.career_is_complete = True

    # Проектная анкета
    if body.project_role is not None:
        p.project_role = body.project_role.strip()[:100]
    if body.project_skills is not None:
        p.project_skills = body.project_skills.strip()[:1000]
    if body.project_bio is not None:
        p.project_bio = body.project_bio.strip()[:2000]

    if p.project_role and (p.project_skills or p.project_bio):
        p.project_is_complete = True

    p.is_complete = bool(p.name and p.year and p.major and (p.photos or p.avatar_file_id))
    await db.commit()
    await db.refresh(p)

    raw_interest_ids = p.interest_ids
    if isinstance(raw_interest_ids, str):
        try:
            raw_interest_ids = json.loads(raw_interest_ids)
        except Exception:
            raw_interest_ids = []
    elif not isinstance(raw_interest_ids, list):
        raw_interest_ids = list(raw_interest_ids) if raw_interest_ids else []

    return {
        "status": "ok",
        "message": "Анкета успешно сохранена",
        "profile": {
            "name": p.name,
            "age": p.age,
            "year": p.year,
            "major": p.major,
            "goal": p.goal,
            "custom_interests": p.custom_interests,
            "interest_ids": raw_interest_ids,
            "gender": p.gender,
            "target_gender": p.target_gender,
            "career_goal": p.career_goal,
            "career_custom_skills": p.career_custom_skills,
            "career_work_format": p.career_work_format,
            "career_portfolio_url": p.career_portfolio_url,
            "career_is_complete": p.career_is_complete,
            "is_complete": p.is_complete,
        }
    }



# ─── API: Загрузка и удаление фото профиля ──────────────────
class PhotoDeleteRequest(BaseModel):
    index: Optional[int] = None
    photo_url: Optional[str] = None


@router.post("/api/webapp/profile/photos")
async def webapp_upload_profile_photo(
    photo: UploadFile = File(...),
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Загрузка новой фотографии в галерею профиля студента (максимум 6 фото)."""
    p = student.profile if "profile" in student.__dict__ else None
    if p is None:
        u_full = await get_user(db, student.id)
        p = u_full.profile if u_full else None
    if not p:
        raise HTTPException(status_code=404, detail="Профиль не найден")

    current_photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])
    current_photos = [x for x in current_photos if x]
    if len(current_photos) >= 6:
        raise HTTPException(status_code=400, detail="Достигнут лимит: максимум 6 фотографий в профиле")

    from web.utils.uploads import save_avatar_upload
    photo_url = await save_avatar_upload(photo)
    if not photo_url:
        raise HTTPException(status_code=400, detail="Неверный формат или размер файла (поддерживаются JPG, PNG, WEBP до 10MB)")

    current_photos.append(photo_url)
    p.photos = current_photos
    if not p.avatar_file_id:
        p.avatar_file_id = photo_url

    await db.commit()

    resolved_photos = [resolve_photo_url(pid) for pid in p.photos if resolve_photo_url(pid)]
    return {
        "status": "ok",
        "photos": resolved_photos,
        "photo_url": resolve_photo_url(photo_url),
    }


@router.delete("/api/webapp/profile/photos")
async def webapp_delete_profile_photo(
    payload: PhotoDeleteRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Удаление фотографии из профиля студента."""
    p = student.profile if "profile" in student.__dict__ else None
    if p is None:
        u_full = await get_user(db, student.id)
        p = u_full.profile if u_full else None
    if not p:
        raise HTTPException(status_code=404, detail="Профиль не найден")

    current_photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])
    current_photos = [x for x in current_photos if x]

    removed = False
    if payload.index is not None and 0 <= payload.index < len(current_photos):
        del current_photos[payload.index]
        removed = True
    elif payload.photo_url:
        target = payload.photo_url.strip()
        new_list = []
        for item in current_photos:
            if not removed and (item == target or resolve_photo_url(item) == target or os.path.basename(item) == os.path.basename(target)):
                removed = True
                continue
            new_list.append(item)
        current_photos = new_list

    if not removed:
        raise HTTPException(status_code=404, detail="Фотография не найдена")

    p.photos = current_photos
    if current_photos:
        p.avatar_file_id = current_photos[0]
    else:
        p.photos = []
        p.avatar_file_id = None

    await db.commit()

    resolved_photos = [resolve_photo_url(pid) for pid in current_photos if resolve_photo_url(pid)]
    return {
        "status": "ok",
        "photos": resolved_photos,
    }


# ─── API: Настройки приватности профиля ──────────────────────
class PrivacyUpdateRequest(BaseModel):
    online_visibility: Optional[str] = None
    message_permission: Optional[str] = None
    allow_employer_access: Optional[bool] = None
    hide_age: Optional[bool] = None
    hide_course: Optional[bool] = None
    hide_email: Optional[bool] = None


class PhotoToggleRequest(BaseModel):
    photo_id: str


@router.get("/api/webapp/privacy")
async def webapp_get_privacy(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Получить текущие настройки приватности профиля."""
    privacy = await get_or_create_user_privacy(db, student.id)
    p = student.profile if "profile" in student.__dict__ else None
    if p is None:
        u_full = await get_user(db, student.id)
        p = u_full.profile if u_full else None
    photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
    photos = [x for x in photos if x]
    priv_photos_set = set(privacy.private_photos or [])

    photos_meta = []
    for idx, pid in enumerate(photos):
        url = resolve_photo_url(pid)
        if not url:
            continue
        photos_meta.append({
            "id": str(pid),
            "url": url,
            "is_main": (idx == 0),
            "is_private": bool(idx > 0 and str(pid).strip() in priv_photos_set),
        })

    return {
        "status": "ok",
        "privacy": {
            "online_visibility": privacy.online_visibility or "all",
            "message_permission": privacy.message_permission or "matches",
            "allow_employer_access": bool(privacy.allow_employer_access),
            "hide_age": bool(privacy.hide_age),
            "hide_course": bool(privacy.hide_course),
            "hide_email": bool(privacy.hide_email),
            "private_photos": privacy.private_photos or [],
        },
        "photos": photos_meta,
    }


@router.post("/api/webapp/privacy")
async def webapp_update_privacy(
    payload: PrivacyUpdateRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Обновить настройки приватности профиля."""
    update_data = {}
    if payload.online_visibility in ("all", "matches", "nobody"):
        update_data["online_visibility"] = payload.online_visibility
    if payload.message_permission in ("matches", "verified_only", "nobody"):
        update_data["message_permission"] = payload.message_permission
    if payload.allow_employer_access is not None:
        update_data["allow_employer_access"] = payload.allow_employer_access
    if payload.hide_age is not None:
        update_data["hide_age"] = payload.hide_age
    if payload.hide_course is not None:
        update_data["hide_course"] = payload.hide_course
    if payload.hide_email is not None:
        update_data["hide_email"] = payload.hide_email

    privacy = await update_user_privacy(db, student.id, **update_data)
    return {
        "status": "ok",
        "message": "Настройки приватности успешно сохранены",
        "privacy": {
            "online_visibility": privacy.online_visibility or "all",
            "message_permission": privacy.message_permission or "matches",
            "allow_employer_access": bool(privacy.allow_employer_access),
            "hide_age": bool(privacy.hide_age),
            "hide_course": bool(privacy.hide_course),
            "hide_email": bool(privacy.hide_email),
            "private_photos": privacy.private_photos or [],
        },
    }


@router.post("/api/webapp/privacy/photo-toggle")
async def webapp_toggle_photo_privacy(
    payload: PhotoToggleRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Переключить приватность конкретного дополнительного фото."""
    clean_id = payload.photo_id.strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Не указан ID фото")

    # Проверяем, не является ли это фото главным
    p = student.profile if "profile" in student.__dict__ else None
    if p is None:
        u_full = await get_user(db, student.id)
        p = u_full.profile if u_full else None
    photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
    if photos and str(photos[0]).strip() == clean_id:
        raise HTTPException(status_code=400, detail="Главное фото всегда остаётся открытым")

    privacy, is_now_private = await toggle_photo_privacy(db, student.id, clean_id)
    return {
        "status": "ok",
        "photo_id": clean_id,
        "is_private": is_now_private,
        "private_photos": privacy.private_photos or [],
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
    if payload.mode == "career":
        new_mode = ModeEnum.career
    elif payload.mode == "projects":
        new_mode = ModeEnum.projects
    else:
        new_mode = ModeEnum.dating
    student.mode = new_mode
    await db.commit()
    return {"status": "ok", "mode": new_mode.value}


# ─── API: Отправка рейтинга из суперлайков ────────────────────
class SendRatingRequest(BaseModel):
    target_user_id: int


@router.post("/api/webapp/profile/send_rating")
async def webapp_send_rating(
    payload: SendRatingRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Отправить 1 балл рейтинга из имеющихся суперлайков студента другому пользователю.
    Списывает 1 суперлайк у student, прибавляет +1.0 к Profile.rating_score получателя
    и отправляет ему уведомление в Telegram.
    """
    if payload.target_user_id == student.id:
        raise HTTPException(status_code=400, detail="Нельзя отправить рейтинг самому себе")

    result = await transfer_superlike_rating(db, student.id, payload.target_user_id)
    if not result.get("success"):
        error = result.get("error")
        if error == "insufficient_balance":
            raise HTTPException(status_code=400, detail="Недостаточно суперлайков на балансе")
        elif error == "target_not_found":
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        elif error == "self_transfer_forbidden":
            raise HTTPException(status_code=400, detail="Нельзя отправить рейтинг самому себе")
        else:
            raise HTTPException(status_code=400, detail="Не удалось отправить рейтинг")

    # Отправляем уведомление получателю в Telegram
    try:
        from aiogram import Bot
        bot = Bot(token=settings.BOT_TOKEN)
        sender_name = html.escape(result.get("sender_name") or "Студент")
        await bot.send_message(
            chat_id=payload.target_user_id,
            text=f"⭐ <b>{sender_name}</b> отправил(а) тебе суперлайк (+1 к рейтингу)!",
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception as e:
        logger.warning(f"Failed to notify recipient of superlike rating gift: {e}")

    return {
        "status": "ok",
        "new_target_rating": result.get("new_target_rating"),
        "remaining_superlikes": result.get("remaining_superlikes"),
        "target_name": result.get("target_name"),
    }


# ─── API: StudMatch Career Networking ───────────────────────
class CareerProfileUpdateRequest(BaseModel):
    career_goal: Optional[str] = None
    career_custom_skills: Optional[str] = None
    career_portfolio_url: Optional[str] = None
    career_work_format: Optional[str] = None
    career_avatar_file_id: Optional[str] = None


@router.post("/api/webapp/profile/career")
async def webapp_update_career_profile(
    payload: CareerProfileUpdateRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Быстрое сохранение карьерных данных студента (StudMatch)."""
    p_res = await db.execute(select(Profile).where(Profile.user_id == student.id))
    p = p_res.scalar_one_or_none()
    if not p:
        p = Profile(user_id=student.id, name=student.tg_username or "Студент")
        db.add(p)

    if payload.career_goal is not None:
        p.career_goal = payload.career_goal.strip()
    if payload.career_custom_skills is not None:
        p.career_custom_skills = payload.career_custom_skills.strip()
    if payload.career_portfolio_url is not None:
        p.career_portfolio_url = payload.career_portfolio_url.strip()
    if payload.career_work_format is not None:
        p.career_work_format = payload.career_work_format.strip()
    if payload.career_avatar_file_id is not None:
        p.career_avatar_file_id = payload.career_avatar_file_id.strip() if payload.career_avatar_file_id else None

    p.career_is_complete = True
    await db.commit()
    await db.refresh(p)

    return {
        "status": "ok",
        "message": "Карьерный профиль StudMatch обновлен!",
        "profile": {
            "career_goal": p.career_goal,
            "career_custom_skills": p.career_custom_skills,
            "career_portfolio_url": p.career_portfolio_url,
            "career_work_format": p.career_work_format,
            "career_avatar_file_id": p.career_avatar_file_id,
            "career_avatar_url": resolve_photo_url(p.career_avatar_file_id) if p.career_avatar_file_id else None,
            "career_is_complete": p.career_is_complete,
        },
    }


@router.get("/api/webapp/career/feed")
async def webapp_career_feed(
    q: Optional[str] = None,
    category: Optional[str] = "all",
    work_format: Optional[str] = "all",
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Профессиональная лента нетворкинга StudMatch:
    Возвращает карточки специалистов/студентов с навыками, целями и портфолио.
    """
    query = (
        select(User)
        .options(selectinload(User.profile), selectinload(User.university))
        .join(Profile, Profile.user_id == User.id)
        .where(
            and_(
                User.id != student.id,
                User.is_active.is_(True),
                or_(
                    Profile.career_is_complete.is_(True),
                    Profile.career_custom_skills.isnot(None),
                    Profile.career_goal.isnot(None),
                    Profile.is_complete.is_(True),
                ),
            )
        )
    )

    # 1. Текстовый поиск по q (имя, вуз, навыки, цель)
    if q and q.strip():
        q_clean = q.strip()
        query = query.where(
            or_(
                Profile.name.ilike(f"%{q_clean}%"),
                Profile.career_custom_skills.ilike(f"%{q_clean}%"),
                Profile.career_goal.ilike(f"%{q_clean}%"),
                User.university.has(University.name.ilike(f"%{q_clean}%")),
                User.university.has(University.short_name.ilike(f"%{q_clean}%")),
            )
        )

    # 2. Фильтрация по категориям
    category_keywords = {
        "it": ["python", "java", "c++", "c#", "frontend", "backend", "fullstack", "react", "vue", "docker", "devops", "sql", "код", "разраб", "web dev", "web-dev", "flutter", "ios", "android", "разработ"],
        "design": ["дизайн", "design", "ux", "ui", "figma", "иллюстра", "3d", "blender", "photoshop", "графич", "моушн"],
        "marketing": ["маркетинг", "marketing", "smm", "target", "реклама", "pr", "контент", "копирайт", "трафик", "seo", "бренд"],
        "management": ["менеджмент", "management", "pm", "управлен", "продакт", "проджект", "лидер", "бизнес", "sales", "продаж"],
        "data": ["data", "данн", "аналит", "ml", "ai", "machine learning", "datascience", "sql", "pandas", "bi", "нейросет"],
    }

    if category and category.lower() in category_keywords:
        kw_list = category_keywords[category.lower()]
        conds = [
            or_(
                Profile.career_custom_skills.ilike(f"%{kw}%"),
                Profile.career_goal.ilike(f"%{kw}%"),
                Profile.major.ilike(f"%{kw}%"),
            )
            for kw in kw_list
        ]
        query = query.where(or_(*conds))

    # 3. Фильтрация по формату работы
    if work_format and work_format != "all":
        query = query.where(Profile.career_work_format.ilike(f"%{work_format}%"))

    # Сортировка: сначала премиум, затем буст, затем рейтинг
    query = query.order_by(
        User.premium_until.desc().nullslast(),
        User.boost_until.desc().nullslast(),
        Profile.rating_score.desc().nullslast(),
        User.created_at.desc(),
    ).limit(35)

    res = await db.execute(query)
    candidates = list(res.scalars().all())

    cand_ids = [c.id for c in candidates]
    connected_ids = set()
    unlocked_ids = set()
    pending_ids = set()

    if cand_ids:
        # Взаимные мэтчи (уже подключены)
        m_stmt = select(Match).where(
            or_(
                and_(Match.user1_id == student.id, Match.user2_id.in_(cand_ids)),
                and_(Match.user2_id == student.id, Match.user1_id.in_(cand_ids)),
            )
        )
        m_res = await db.execute(m_stmt)
        for m in m_res.scalars().all():
            other_id = m.user2_id if m.user1_id == student.id else m.user1_id
            connected_ids.add(other_id)
            if m.is_tg_unlocked:
                unlocked_ids.add(other_id)

        # Отправленные свайпы / запросы
        s_stmt = select(Swipe.to_user_id).where(
            and_(
                Swipe.from_user_id == student.id,
                Swipe.to_user_id.in_(cand_ids),
                Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
            )
        )
        s_res = await db.execute(s_stmt)
        for sid in s_res.scalars().all():
            if sid not in connected_ids:
                pending_ids.add(sid)

    cards = []
    for u in candidates:
        p = u.profile
        if not p:
            continue

        if p.career_avatar_file_id:
            photos = [p.career_avatar_file_id]
        else:
            photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])

        photo_urls = [resolve_photo_url(pid) for pid in photos if resolve_photo_url(pid)]
        if not photo_urls:
            photo_urls = [DEFAULT_FALLBACK_AVATAR]

        # Парсим навыки
        skills = []
        if p.career_custom_skills:
            for s in p.career_custom_skills.replace(";", ",").split(","):
                s_clean = s.strip()
                if s_clean and len(s_clean) < 30:
                    skills.append(s_clean)
        elif p.career_skills:
            skills = [f"Навык #{sid}" for sid in list(p.career_skills)[:6]]

        # Если явных карьерных навыков нет — берем интересы
        if not skills and p.interest_ids:
            tag_res = await db.execute(select(InterestTag.name).where(InterestTag.id.in_(p.interest_ids[:5])))
            skills = list(tag_res.scalars().all())

        is_connected = u.id in connected_ids
        is_pending = u.id in pending_ids

        u_priv = u.privacy if (u and "privacy" in u.__dict__) else None
        if not u_priv and u:
            u_priv = await get_or_create_user_privacy(db, u.id)
        hide_age = getattr(u_priv, "hide_age", False)
        hide_course = getattr(u_priv, "hide_course", False)

        cards.append({
            "user_id": u.id,
            "name": p.name or "Студент",
            "age": None if hide_age else p.age,
            "year": None if hide_course else p.year,
            "hide_age": hide_age,
            "hide_course": hide_course,
            "major": p.major or "",
            "university": (u.university.short_name or u.university.name) if u.university else "",
            "photos": photo_urls,
            "avatar_url": photo_urls[0],
            "career_goal": p.career_goal or "Открыт к вакансиям и стажировкам в компаниях 💼",
            "career_skills": skills[:8],
            "career_work_format": p.career_work_format or "Удалённо / Офис",
            "career_portfolio_url": p.career_portfolio_url,
            "rating_score": round(p.rating_score or 0.0, 1),
            "is_verified": bool(u.is_verified),
            "is_premium": bool(u.is_premium),
            "is_connected": is_connected,
            "is_pending": is_pending,
            "tg_username": u.tg_username if (u.id in unlocked_ids) else None,
        })

    return {
        "status": "ok",
        "count": len(cards),
        "candidates": cards,
    }


# ─── API: Проекты и стартапы (Желтая лента «Проекты») ───
class ProjectCreateRequest(BaseModel):
    title: str
    pitch: str
    description: str
    stage: Optional[str] = "idea"
    required_roles: Optional[Union[List[str], str]] = []
    conditions: Optional[str] = None
    demo_url: Optional[str] = None
    pitchdeck_url: Optional[str] = None
    cover_url: Optional[str] = None

    @field_validator("required_roles", mode="before")
    @classmethod
    def parse_required_roles(cls, v):
        if isinstance(v, str):
            return [r.strip() for r in v.split(",") if r.strip()]
        if isinstance(v, list):
            return [str(r).strip() for r in v if str(r).strip()]
        return []

    @field_validator("demo_url", "pitchdeck_url", "cover_url", "conditions", mode="before")
    @classmethod
    def clean_empty_strings(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ProjectSwipeRequest(BaseModel):
    project_id: str
    action: str  # "like", "superlike", "skip"
    comment: Optional[str] = None


class FounderCandidateSwipeRequest(BaseModel):
    candidate_id: Optional[int] = None
    candidate_user_id: Optional[int] = None
    action: str  # "like", "skip"


class ProjectProfileUpdateRequest(BaseModel):
    project_role: Optional[str] = None
    project_skills: Optional[str] = None
    project_bio: Optional[str] = None


@router.get("/api/webapp/projects/feed")
async def webapp_projects_feed(
    q: Optional[str] = None,
    stage: Optional[str] = "all",
    role: Optional[str] = "all",
    catalog: bool = False,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Лента студенческих проектов и стартапов:
    Возвращает карточки проектов для свайп-колоды и каталога с фильтрацией.
    При catalog=True возвращаются все проекты (включая свои и те, на которые уже был свайп).
    """
    exclude_swiped = not catalog
    exclude_own = not catalog

    projects = await get_projects_feed(
        db=db,
        viewer_user_id=student.id,
        q=q,
        stage=stage,
        role=role,
        exclude_swiped=exclude_swiped,
        exclude_own=exclude_own,
    )

    # Получаем список ID проектов, на которые текущий студент уже откликнулся/свайпнул
    swiped_stmt = select(Swipe.to_project_id).where(
        and_(
            Swipe.from_user_id == student.id,
            Swipe.to_project_id.isnot(None),
        )
    )
    swiped_res = await db.execute(swiped_stmt)
    swiped_pids = set(swiped_res.scalars().all())

    # Получаем список ID проектов, по которым уже есть взаимный Match
    matched_stmt = select(Match.project_id).where(
        and_(
            Match.mode == ModeEnum.projects,
            or_(Match.user1_id == student.id, Match.user2_id == student.id),
            Match.project_id.isnot(None),
        )
    )
    matched_res = await db.execute(matched_stmt)
    matched_pids = set(matched_res.scalars().all())

    cards = []
    for proj in projects:
        u = proj.user
        p = u.profile if u else None
        founder_photos = list(p.photos) if (p and p.photos) else ([p.avatar_file_id] if (p and p.avatar_file_id) else [])
        avatar_url = resolve_photo_url(founder_photos[0]) if founder_photos else DEFAULT_FALLBACK_AVATAR
        uni_name = (u.university.short_name or u.university.name) if (u and u.university) else ""
        is_my_proj = proj.user_id == student.id
        is_swiped = proj.id in swiped_pids
        is_matched = proj.id in matched_pids

        cards.append({
            "id": str(proj.id),
            "user_id": proj.user_id,
            "founder_id": proj.user_id,
            "is_my_project": is_my_proj,
            "is_swiped": is_swiped,
            "is_matched": is_matched,
            "founder_name": p.name if (p and p.name) else "Фаундер",
            "founder_university": uni_name,
            "founder_avatar": avatar_url,
            "founder_role": p.project_role if p else None,
            "founder_rating": round(p.rating_score or 0.0, 1) if p else 0.0,
            "founder_verified": bool(u.is_verified) if u else False,
            "founder": {
                "id": proj.user_id,
                "name": p.name if (p and p.name) else "Фаундер",
                "university": uni_name,
                "avatar_url": avatar_url,
                "role": p.project_role if p else None,
                "rating": round(p.rating_score or 0.0, 1) if p else 0.0,
                "verified": bool(u.is_verified) if u else False,
            },
            "title": proj.title,
            "pitch": proj.pitch,
            "description": proj.description,
            "stage": proj.stage,
            "required_roles": proj.required_roles or [],
            "conditions": proj.conditions or "По договорённости",
            "demo_url": proj.demo_url,
            "pitchdeck_url": proj.pitchdeck_url,
            "cover_url": proj.cover_url or avatar_url,
            "created_at": proj.created_at.isoformat() if proj.created_at else None,
        })

    return {
        "status": "ok",
        "count": len(cards),
        "projects": cards,
    }


@router.post("/api/webapp/projects/swipe")
async def webapp_projects_swipe(
    payload: ProjectSwipeRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Свайп проекта кандидатом (Хочу в команду / Скип / Суперлайк)."""
    try:
        p_uuid = uuid.UUID(payload.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный ID проекта")

    project = await get_project(db, p_uuid)
    if not project or not project.is_active:
        raise HTTPException(status_code=404, detail="Проект не найден или скрыт")

    if project.user_id == student.id:
        raise HTTPException(status_code=400, detail="Нельзя свайпать собственный проект")

    action_map = {
        "like": SwipeAction.like,
        "superlike": SwipeAction.superlike,
        "skip": SwipeAction.skip,
    }
    action = action_map.get(payload.action.lower(), SwipeAction.skip)

    await create_swipe(
        db,
        from_id=student.id,
        to_id=project.user_id,
        action=action,
        mode=ModeEnum.projects,
        comment=payload.comment,
        to_project_id=p_uuid,
    )

    if action in (SwipeAction.like, SwipeAction.superlike):
        cand_name = student.profile.name if student.profile and student.profile.name else "Студент"
        cand_major = student.profile.major if student.profile and student.profile.major else ""
        note = f"\n💬 <i>«{html.escape(payload.comment)}»</i>" if payload.comment else ""
        msg = (
            f"💡 <b>Новый отклик в проект «{html.escape(project.title)}»!</b>\n\n"
            f"👤 <b>{html.escape(cand_name)}</b> ({html.escape(cand_major)})\n"
            f"хочет присоединиться к вашей команде.{note}\n\n"
            f"👉 Откройте раздел «Мои проекты» в WebApp или боте, чтобы посмотреть анкету и принять отклик!"
        )
        try:
            from aiogram import Bot
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(project.user_id, msg, parse_mode="HTML")
            await bot.session.close()
        except Exception:
            pass

    return {"status": "ok", "action": action.value}


@router.get("/api/webapp/projects/my")
async def webapp_get_my_projects(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Список проектов текущего пользователя с количеством откликов."""
    projects = await get_user_projects(db, student.id, only_active=False)
    data = []
    for proj in projects:
        candidates = await get_project_candidates(db, proj.id)
        data.append({
            "id": str(proj.id),
            "title": proj.title,
            "pitch": proj.pitch,
            "description": proj.description,
            "stage": proj.stage,
            "required_roles": proj.required_roles or [],
            "conditions": proj.conditions,
            "demo_url": proj.demo_url,
            "pitchdeck_url": proj.pitchdeck_url,
            "cover_url": proj.cover_url,
            "is_active": proj.is_active,
            "candidates_count": len(candidates),
            "created_at": proj.created_at.isoformat() if proj.created_at else None,
        })
    return {"status": "ok", "projects": data}


@router.post("/api/webapp/projects")
async def webapp_create_project(
    payload: ProjectCreateRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Создать новый проект (максимум 3 активных проекта на пользователя)."""
    my_active = await get_user_projects(db, student.id, only_active=True)
    if len(my_active) >= 3:
        raise HTTPException(status_code=400, detail="Вы можете создать максимум 3 активных проекта")

    if not payload.title.strip() or not payload.pitch.strip() or not payload.description.strip():
        raise HTTPException(status_code=400, detail="Заполните название, краткий питч и описание проекта")

    project = await create_project(
        db=db,
        user_id=student.id,
        title=payload.title,
        pitch=payload.pitch,
        description=payload.description,
        stage=payload.stage or "idea",
        required_roles=payload.required_roles or [],
        conditions=payload.conditions,
        demo_url=payload.demo_url,
        pitchdeck_url=payload.pitchdeck_url,
        cover_url=payload.cover_url,
    )
    return {"status": "ok", "project_id": str(project.id)}


@router.put("/api/webapp/projects/{project_id}")
async def webapp_update_project(
    project_id: str,
    payload: ProjectCreateRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Редактировать существующий проект."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный ID проекта")

    updated = await update_project(
        db=db,
        project_id=p_uuid,
        user_id=student.id,
        title=payload.title.strip(),
        pitch=payload.pitch.strip(),
        description=payload.description.strip(),
        stage=payload.stage or "idea",
        required_roles=payload.required_roles or [],
        conditions=payload.conditions,
        demo_url=payload.demo_url,
        pitchdeck_url=payload.pitchdeck_url,
        cover_url=payload.cover_url,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Проект не найден или нет прав")
    return {"status": "ok", "project_id": str(updated.id)}


@router.delete("/api/webapp/projects/{project_id}")
async def webapp_delete_project(
    project_id: str,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Удалить проект."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный ID проекта")

    deleted = await delete_project(db, p_uuid, student.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Проект не найден или нет прав")
    return {"status": "ok"}


@router.post("/api/webapp/projects/upload_deck")
async def webapp_upload_project_deck(
    file: UploadFile = File(...),
    student: User = Depends(get_current_student),
):
    """Загрузка PDF-питчдека или презентации для проекта."""
    raw_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "pdf"
    if raw_ext not in ("pdf", "png", "jpg", "jpeg"):
        raise HTTPException(status_code=400, detail="Поддерживаются форматы PDF, PNG, JPG")

    file_bytes = await file.read()
    if len(file_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Максимальный размер файла — 20 МБ")

    try:
        from bot.utils.minio_client import upload_document
        url = await upload_document(file_bytes, file.filename, student.id)
        return {"status": "ok", "url": url}
    except Exception as e:
        logger.warning(f"MinIO upload error: {e}. Fallback to local storage.")
        local_dir = os.path.abspath("web/static/uploads/projects")
        os.makedirs(local_dir, exist_ok=True)
        fname = f"{student.id}_{uuid.uuid4().hex[:8]}.{raw_ext}"
        local_path = os.path.join(local_dir, fname)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        return {"status": "ok", "url": f"/static/uploads/projects/{fname}"}


@router.get("/api/webapp/projects/{project_id}/candidates")
async def webapp_get_project_candidates(
    project_id: str,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Кандидаты, откликнувшиеся на проект (колода для фаундера)."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный ID проекта")

    project = await get_project(db, p_uuid)
    if not project or project.user_id != student.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён: вы не автор проекта")

    candidates_with_swipes = await get_project_candidates(db, p_uuid)
    data = []
    for cand_user, swipe in candidates_with_swipes:
        p = cand_user.profile
        if not p:
            continue
        c_photos = list(p.photos) if p.photos else ([p.avatar_file_id] if p.avatar_file_id else [])
        photo_urls = [resolve_photo_url(pid) for pid in c_photos if resolve_photo_url(pid)] or [DEFAULT_FALLBACK_AVATAR]
        uni_name = (cand_user.university.short_name or cand_user.university.name) if cand_user.university else ""

        data.append({
            "user_id": cand_user.id,
            "name": p.name or "Студент",
            "age": p.age,
            "year": p.year,
            "major": p.major or "",
            "university": uni_name,
            "avatar_url": photo_urls[0],
            "photos": photo_urls,
            "project_role": p.project_role or p.major,
            "project_skills": p.project_skills or p.career_custom_skills or "",
            "project_bio": p.project_bio or p.career_goal or p.goal or "",
            "comment": swipe.comment,
            "action": swipe.action.value,
            "swiped_at": swipe.created_at.isoformat() if swipe.created_at else None,
            "rating_score": round(p.rating_score or 0.0, 1),
            "is_verified": bool(cand_user.is_verified),
        })

    return {"status": "ok", "candidates": data}


@router.post("/api/webapp/projects/{project_id}/swipe_candidate")
async def webapp_founder_swipe_candidate(
    project_id: str,
    payload: FounderCandidateSwipeRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Фаундер одобряет (лайкает) или пропускает кандидата."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный ID проекта")

    cand_id = payload.candidate_id or payload.candidate_user_id
    if not cand_id:
        raise HTTPException(status_code=400, detail="Не указан ID кандидата")

    project = await get_project(db, p_uuid)
    if not project or project.user_id != student.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён: вы не автор проекта")

    action = SwipeAction.like if payload.action.lower() == "like" else SwipeAction.skip
    is_match = await founder_swipe_candidate(
        db=db,
        founder_id=student.id,
        candidate_id=cand_id,
        project_id=p_uuid,
        action=action,
    )

    match_id_str = None
    if is_match:
        m = await get_match_between_users(db, student.id, cand_id, ModeEnum.projects)
        if m:
            match_id_str = str(m.id)

        # Уведомление кандидату в Telegram с кнопками
        cand = await get_user(db, cand_id)
        founder_name = student.profile.name if student.profile and student.profile.name else "Фаундер"
        if cand:
            msg = (
                f"🎉 <b>Вас приняли в команду проекта «{html.escape(project.title)}»!</b>\n\n"
                f"Фаундер <b>{html.escape(founder_name)}</b> ответил взаимностью на ваш отклик.\n"
                f"Чат команды уже открыт в WebApp СтудМэч! 🚀"
            )
            try:
                from aiogram import Bot
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                from aiogram.types import WebAppInfo
                bot = Bot(token=settings.BOT_TOKEN)
                kb_builder = InlineKeyboardBuilder()
                if student.tg_username:
                    clean_u = student.tg_username.lstrip("@")
                    kb_builder.button(text=f"✈️ Telegram фаундера (@{clean_u})", url=f"https://t.me/{clean_u}")
                kb_builder.button(
                    text="💬 Открыть чат в приложении",
                    web_app=WebAppInfo(url=f"{settings.webapp_url}?startapp=chat_{student.id}")
                )
                kb_builder.adjust(1)
                await bot.send_message(cand.id, msg, parse_mode="HTML", reply_markup=kb_builder.as_markup())
                await bot.session.close()
            except Exception as e:
                logger.warning(f"Failed to send candidate acceptance message: {e}")

    return {
        "status": "ok",
        "is_match": is_match,
        "match_id": match_id_str,
        "match": {"id": match_id_str, "match_id": match_id_str} if match_id_str else None,
    }


@router.post("/api/webapp/profile/project")
async def webapp_update_project_profile(
    payload: ProjectProfileUpdateRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Обновление проектной анкеты студента."""
    p = await get_or_create_profile(db, student.id)
    if payload.project_role is not None:
        p.project_role = payload.project_role.strip()
    if payload.project_skills is not None:
        p.project_skills = payload.project_skills.strip()
    if payload.project_bio is not None:
        p.project_bio = payload.project_bio.strip()

    p.project_is_complete = bool(p.project_role and (p.project_skills or p.project_bio))
    await db.commit()
    return {
        "status": "ok",
        "project_role": p.project_role,
        "project_skills": p.project_skills,
        "project_bio": p.project_bio,
        "project_is_complete": p.project_is_complete,
    }


# ─── API: Поисковые фильтры (Возраст, Курс, Факультет, Пол) ───
class WebAppFiltersRequest(BaseModel):
    min_age: int = 16
    max_age: int = 35
    min_year: int = 1
    max_year: int = 6
    major: Optional[str] = "all"
    gender: Optional[str] = "all"  # "all", "female", "male"


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
        "gender": p.target_gender if (p and p.target_gender) else "all",
    }


@router.post("/api/webapp/filters")
async def webapp_save_filters(
    payload: WebAppFiltersRequest,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить фильтры поиска (возраст, курс, факультет, пол)."""
    p = student.profile
    if p:
        p.filter_min_age = max(16, min(50, payload.min_age))
        p.filter_max_age = max(payload.min_age, min(50, payload.max_age))
        p.filter_min_year = max(1, min(6, payload.min_year))
        p.filter_max_year = max(payload.min_year, min(6, payload.max_year))
        p.filter_major = None if payload.major in ("all", "", None) else payload.major.strip()
        if payload.gender in ("all", "female", "male"):
            p.target_gender = payload.gender
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
    if not p:
        p = await get_profile(db, target.id)

    raw_photos = p.photos if p else None
    if isinstance(raw_photos, str):
        try:
            import json
            parsed = json.loads(raw_photos)
            photos = list(parsed) if isinstance(parsed, (list, tuple)) else [parsed]
        except Exception:
            photos = [raw_photos]
    elif isinstance(raw_photos, (list, tuple)):
        photos = list(raw_photos)
    elif p and p.avatar_file_id:
        photos = [p.avatar_file_id]
    else:
        photos = []
    photos = [x for x in photos if x]

    career_avatar_url = resolve_photo_url(p.career_avatar_file_id) if (p and p.career_avatar_file_id) else None
    career_photos = [career_avatar_url] if career_avatar_url else [resolve_photo_url(x) for x in photos if resolve_photo_url(x)]
    career_photos = [u for u in career_photos if u]
    if not career_photos:
        career_photos = [DEFAULT_FALLBACK_AVATAR]

    tags = []
    tag_ids = p.interest_ids if (p and p.interest_ids) else []
    if isinstance(tag_ids, str):
        try:
            tag_ids = json.loads(tag_ids)
        except Exception:
            tag_ids = []
    if tag_ids:
        tag_res = await db.execute(select(InterestTag).where(InterestTag.id.in_(tag_ids)))
        for t in tag_res.scalars().all():
            tags.append({"id": t.id, "name": t.name, "emoji": t.emoji})

    # Проверяем обоюдное открытие контактов и наличие мэтча
    is_me = (student.id == target.id)
    m = None
    has_match = False
    match_id = None
    is_tg_unlocked = False

    if not is_me:
        cur_mode = student.mode if hasattr(student, "mode") else None
        m = await get_match_between_users(db, student.id, target.id, mode=cur_mode)
        if not m:
            m = await get_match_between_users(db, student.id, target.id)
        if m:
            has_match = True
            match_id = str(m.id)
            if m.is_tg_unlocked:
                is_tg_unlocked = True

    target_privacy = target.privacy if (target and "privacy" in target.__dict__) else None
    if not target_privacy and target:
        target_privacy = await get_or_create_user_privacy(db, target.id)

    hide_age = getattr(target_privacy, "hide_age", False) if not is_me else False
    hide_course = getattr(target_privacy, "hide_course", False) if not is_me else False
    priv_photos_set = set(target_privacy.private_photos or [])

    photos_meta = []
    for idx, pid in enumerate(photos):
        url = resolve_photo_url(pid)
        if not url:
            continue
        is_priv = bool(idx > 0 and str(pid).strip() in priv_photos_set and not has_match and not is_me)
        photos_meta.append({
            "id": str(pid),
            "url": url,
            "is_main": (idx == 0),
            "is_private": is_priv,
        })
    if not photos_meta:
        photos_meta = [{"id": "fallback", "url": DEFAULT_FALLBACK_AVATAR, "is_main": True, "is_private": False}]
    photo_urls = [pm["url"] for pm in photos_meta]

    msg_perm = target_privacy.message_permission or "matches"
    can_send_message = True
    message_block_reason = ""
    if msg_perm == "nobody":
        can_send_message = False
        message_block_reason = "Пользователь ограничил входящие сообщения 🔒"
    elif msg_perm == "verified_only" and not getattr(student, "email_verified", False):
        can_send_message = False
        message_block_reason = "Сообщения разрешены только верифицированным студентам 🎓"

    return {
        "status": "ok",
        "user": {
            "id": target.id,
            "user_id": target.id,
            "is_me": is_me,
            "has_match": has_match,
            "match_id": match_id,
            "is_tg_unlocked": is_tg_unlocked,
            "name": p.name if p else "Студент",
            "age": None if hide_age else (p.age if p else None),
            "year": None if hide_course else (p.year if p else None),
            "hide_age": hide_age,
            "hide_course": hide_course,
            "is_online": is_user_online_visible_to(student.id, target, is_mutual_match=has_match),
            "online_status_text": get_user_online_status_text_for(student.id, target, is_mutual_match=has_match),
            "major": p.major if p else "",
            "university": (target.university.short_name or target.university.name) if target.university else "",
            "goal": p.goal if p else "",
            "custom_interests": p.custom_interests if p else "",
            "tags": tags,
            "photos": photo_urls,
            "photos_meta": photos_meta,
            "can_send_message": can_send_message,
            "message_block_reason": message_block_reason,
            "career_avatar_url": career_avatar_url,
            "career_photos": career_photos,
            "rating_score": round(p.rating_score or 0.0, 1) if p else 0.0,
            "is_verified": getattr(target, "email_verified", False),
            "is_premium": getattr(target, "is_premium", False),
            "tg_username": target.tg_username if (is_tg_unlocked and not is_me) else None,
            # Карьерные параметры
            "career_goal": p.career_goal if p else None,
            "career_skills": p.career_skills if p else None,
            "career_custom_skills": p.career_custom_skills if p else None,
            "career_portfolio_url": p.career_portfolio_url if p else None,
            "career_work_format": p.career_work_format if p else None,
        }
    }


# ─── API: Зал Славы (Рейтинг / Лидерборд) ──────────────────────
@router.get("/api/webapp/hall_of_fame")
async def webapp_get_hall_of_fame(
    scope: str = Query("all", pattern="^(all|university)$"),
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Возвращает топ-50 студентов в Зале Славы:
    - scope: 'all' (Все ВУЗы) или 'university' (Мой ВУЗ)
    - Позицию текущего пользователя (my_rank) и его рейтинг (my_score)
    """
    has_univ = bool(student.university_id and student.university)
    univ_name = (student.university.short_name or student.university.name) if has_univ else None

    # Если запрошен фильтр по ВУЗу, но у студента нет ВУЗа
    if scope == "university" and not student.university_id:
        my_score = round(student.profile.rating_score or 0.0, 1) if student.profile else 0.0
        return {
            "status": "ok",
            "scope": "university",
            "has_university": False,
            "university_name": None,
            "my_rank": None,
            "my_score": my_score,
            "leaderboard": [],
        }

    # Запрос топ-50 пользователей
    query = (
        select(Profile, User)
        .join(User, Profile.user_id == User.id)
        .options(selectinload(User.university))
        .where(
            User.is_active.is_(True),
            Profile.is_complete.is_(True),
            Profile.is_visible.is_(True),
        )
    )

    if scope == "university":
        query = query.where(User.university_id == student.university_id)

    query = query.order_by(
        desc(func.coalesce(Profile.rating_score, 0.0)),
        desc(User.email_verified),
        User.created_at.asc(),
    ).limit(50)

    result = await db.execute(query)
    rows = result.all()

    leaderboard = []
    my_rank = None
    my_score = round(student.profile.rating_score or 0.0, 1) if student.profile else 0.0

    for idx, (p, u) in enumerate(rows):
        rank = idx + 1
        is_me = (u.id == student.id)
        if is_me:
            my_rank = rank

        photo_url = resolve_photo_url(p.avatar_file_id)
        if not photo_url and p.photos and len(p.photos) > 0:
            photo_url = resolve_photo_url(p.photos[0])
        if not photo_url:
            photo_url = DEFAULT_FALLBACK_AVATAR

        u_univ_name = ""
        if u.university:
            u_univ_name = u.university.short_name or u.university.name or ""

        leaderboard.append({
            "rank": rank,
            "user_id": u.id,
            "name": p.name or "Студент",
            "age": p.age,
            "university_name": u_univ_name,
            "faculty": p.major,
            "course": p.year,
            "avatar_url": photo_url,
            "rating_score": round(p.rating_score or 0.0, 1),
            "is_verified": bool(u.email_verified),
            "is_premium": bool(u.is_premium),
            "is_me": is_me,
        })

    # Если текущий пользователь не попал в топ-50, вычисляем его реальный ранг
    if my_rank is None and student.profile and student.profile.is_complete and student.profile.is_visible:
        my_raw_score = float(student.profile.rating_score or 0.0)
        my_verified = bool(student.email_verified)
        my_created = student.created_at or datetime.now(timezone.utc)

        rank_query = (
            select(func.count())
            .select_from(Profile)
            .join(User, Profile.user_id == User.id)
            .where(
                User.is_active.is_(True),
                Profile.is_complete.is_(True),
                Profile.is_visible.is_(True),
            )
        )
        if scope == "university":
            rank_query = rank_query.where(User.university_id == student.university_id)

        rank_query = rank_query.where(
            or_(
                func.coalesce(Profile.rating_score, 0.0) > my_raw_score,
                and_(
                    func.coalesce(Profile.rating_score, 0.0) == my_raw_score,
                    User.email_verified > my_verified,
                ),
                and_(
                    func.coalesce(Profile.rating_score, 0.0) == my_raw_score,
                    User.email_verified == my_verified,
                    User.created_at < my_created,
                ),
            )
        )
        ahead_count = await db.scalar(rank_query)
        my_rank = (ahead_count or 0) + 1

    return {
        "status": "ok",
        "scope": scope,
        "has_university": has_univ,
        "university_name": univ_name,
        "my_rank": my_rank,
        "my_score": my_score,
        "leaderboard": leaderboard,
    }


@router.post("/api/webapp/achievements/request-bot-upload")
async def request_bot_achievement_upload(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Отправляет студенту в Telegram диалог загрузки диплома/достижения,
    чтобы обойти блокировки deep-link ссылок внутри Telegram WebView.
    """
    if not student.profile or not student.profile.is_complete:
        return {
            "status": "need_profile",
            "message": "Сначала заполни анкету в боте, чтобы прикреплять дипломы и повышать рейтинг!",
        }
    try:
        from aiogram import Bot
        from bot.keyboards.swipe import achievement_type_keyboard

        bot = Bot(token=settings.BOT_TOKEN)
        text = (
            "📋 <b>Добавление достижения и диплома</b>\n\n"
            "Выбери тип достижения для подтверждения модератором:"
        )
        await bot.send_message(
            chat_id=student.id,
            text=text,
            parse_mode="HTML",
            reply_markup=achievement_type_keyboard(),
        )
        await bot.session.close()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to send achievement prompt to student {student.id}: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/webapp/reset_swipes")
async def webapp_reset_swipes(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Сбросить историю свайпов в текущем режиме для повторного просмотра анкет (пары и чаты сохраняются!)."""
    from sqlalchemy import delete, select, or_, and_, case
    mode = student.mode or ModeEnum.dating

    # Находим ID партнеров, с которыми у пользователя уже есть пара (мэтч)
    matched_partners_subq = select(
        case(
            (Match.user1_id == student.id, Match.user2_id),
            else_=Match.user1_id,
        )
    ).where(
        or_(Match.user1_id == student.id, Match.user2_id == student.id)
    )

    # Удаляем только те свайпы, по которым НЕТ активного мэтча,
    # чтобы вернуть пропущенные анкеты в ленту, но сохранить существующие чаты и взаимные лайки
    await db.execute(
        delete(Swipe).where(
            and_(
                Swipe.from_user_id == student.id,
                or_(Swipe.mode == mode, Swipe.mode.is_(None)),
                ~Swipe.to_user_id.in_(matched_partners_subq),
            )
        )
    )
    # Match и ChatMessage НЕ удаляются ни в коем случае, чтобы не уничтожать переписку!
    await db.commit()
    logger.info(f"User {student.id} reset non-matched swipes in mode {mode} (matches & chats preserved)")
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
    q: Optional[str] = "",
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Поиск пользователя по ID или @username, либо последние 25 пользователей."""
    query = select(User).options(selectinload(User.profile), selectinload(User.university))

    if q and q.strip():
        q_clean = q.strip().lstrip("@")
        if q_clean.isdigit():
            query = query.where(or_(User.id == int(q_clean), User.tg_username.ilike(f"%{q_clean}%")))
        else:
            query = query.where(User.tg_username.ilike(f"%{q_clean}%"))
    else:
        query = query.order_by(desc(User.created_at))

    result = await db.execute(query.limit(25))
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
        if target.is_premium:
            target.premium_until = None
            msg = "Премиум отключен"
        else:
            target.premium_until = datetime.now(timezone.utc) + timedelta(days=365)
            msg = "Премиум активирован на 1 год"

    elif action == "grant_verified":
        target.email_verified = not target.email_verified
        msg = "Статус студента верифицирован" if target.email_verified else "Верификация снята"

    elif action == "add_superlikes":
        target.superlike_balance = (target.superlike_balance or 0) + 10
        msg = f"Начислено +10 суперлайков. Баланс: {target.superlike_balance}"

    await db.commit()
    await db.refresh(target)
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


# ─── API: Служба поддержки (Support Deck) ──────────────────────
@router.get("/api/webapp/support/tickets")
async def webapp_get_support_tickets(
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает историю тикетов поддержки текущего пользователя."""
    res = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == student.id)
        .order_by(SupportTicket.created_at.desc())
    )
    tickets = res.scalars().all()
    items = []
    for t in tickets:
        items.append({
            "id": str(t.id),
            "category": t.category,
            "subject": t.subject,
            "message": t.message,
            "screenshot_url": t.screenshot_url,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "admin_reply": t.admin_reply,
            "created_at": t.created_at.strftime("%d.%m.%Y %H:%M") if t.created_at else "",
            "resolved_at": t.resolved_at.strftime("%d.%m.%Y %H:%M") if t.resolved_at else None,
        })
    return {"status": "ok", "tickets": items}


@router.post("/api/webapp/support/tickets")
async def webapp_create_support_ticket(
    request: Request,
    student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Создает обращение в поддержку (поддерживает multipart/form-data со скриншотом и application/json).
    Отправляет мгновенное уведомление администраторам в Telegram.
    """
    from web.utils.uploads import save_avatar_upload

    category = "other"
    subject = None
    message = ""
    device_info = None
    screenshot_url = None

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        category = str(form.get("category", "other") or "other")
        subject = str(form.get("subject", "") or "") or None
        message = str(form.get("message", "") or "").strip()
        device_info = str(form.get("device_info", "") or "") or None

        screenshot_file = form.get("screenshot")
        if screenshot_file and hasattr(screenshot_file, "filename") and screenshot_file.filename:
            screenshot_url = await save_avatar_upload(screenshot_file)
    else:
        try:
            body = await request.json()
            category = body.get("category", "other") or "other"
            subject = body.get("subject")
            message = str(body.get("message", "") or "").strip()
            device_info = body.get("device_info")
            if isinstance(device_info, dict):
                device_info = json.dumps(device_info, ensure_ascii=False)
            screenshot_url = body.get("screenshot_url")
        except Exception:
            raise HTTPException(status_code=400, detail="Некорректный формат запроса")

    if not message or len(message) < 5:
        raise HTTPException(status_code=400, detail="Сообщение должно содержать не менее 5 символов")

    user_id = student.id
    user_tg_username = student.tg_username

    ticket = SupportTicket(
        user_id=user_id,
        category=category,
        subject=subject,
        message=message,
        screenshot_url=screenshot_url,
        device_info=device_info,
        status=TicketStatus.open,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    # Мгновенный алерт администраторам в Telegram
    try:
        prof_res = await db.execute(select(Profile).where(Profile.user_id == user_id))
        user_p = prof_res.scalar_one_or_none()

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
            user_name = user_p.name if (user_p and user_p.name) else f"Студент {user_id}"
            username_part = f" (@{user_tg_username})" if user_tg_username else ""
            univer_part = f"\n🏫 ВУЗ: {user_p.major or 'Не указан'}" if user_p else ""

            dev_text = "Не определено"
            if device_info:
                try:
                    dev_data = json.loads(device_info) if isinstance(device_info, str) else device_info
                    platform = dev_data.get("platform", "web")
                    res = f"{dev_data.get('screen_width', '?')}x{dev_data.get('screen_height', '?')}"
                    tg_v = dev_data.get("tg_version", "")
                    dev_text = f"{platform.upper()} (Экран {res}, TG: {tg_v})"
                except Exception:
                    dev_text = str(device_info)[:60]

            domain = (settings.DOMAIN or "https://stud-match.ru").rstrip("/")
            alert_text = (
                f"📩 <b>Новое обращение в поддержку #{str(ticket.id)[:8]}</b>\n\n"
                f"👤 <b>Пользователь:</b> {html.escape(user_name)}{username_part} (<code>{student.id}</code>){univer_part}\n"
                f"🏷️ <b>Категория:</b> {cat_title}\n"
                f"📱 <b>Девайс:</b> {html.escape(dev_text)}\n\n"
                f"📝 <b>Сообщение:</b>\n{html.escape(ticket.message)}\n\n"
                f"🔗 <a href='{domain}/admin/support'>Открыть в веб-админке</a>"
            )

            for adm_id in settings.admin_ids:
                try:
                    await bot.send_message(adm_id, alert_text, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as send_err:
                    logger.warning(f"Failed to send support alert to admin {adm_id}: {send_err}")
        finally:
            await bot.session.close()
    except Exception as e:
        logger.warning(f"Error in support ticket notification: {e}")

    return {
        "status": "ok",
        "ticket": {
            "id": str(ticket.id),
            "category": ticket.category,
            "message": ticket.message,
            "screenshot_url": ticket.screenshot_url,
            "status": ticket.status.value,
            "created_at": ticket.created_at.strftime("%d.%m.%Y %H:%M") if ticket.created_at else "",
        }
    }


# ─── API: Администрирование поддержки в Superadmin Hub ─────────
@router.get("/api/webapp/admin/support/tickets")
async def webapp_admin_get_support_tickets(
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
):
    """Список тикетов для мобильного Superadmin Hub."""
    query = (
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.user).selectinload(User.profile),
        )
        .order_by(SupportTicket.created_at.desc())
        .limit(50)
    )
    if status and status in ("open", "in_progress", "resolved", "closed"):
        query = query.where(SupportTicket.status == TicketStatus(status))

    res = await db.execute(query)
    tickets = res.scalars().all()
    items = []
    for t in tickets:
        u_name = t.user.profile.name if (t.user and t.user.profile) else f"ID {t.user_id}"
        items.append({
            "id": str(t.id),
            "user_id": t.user_id,
            "user_name": u_name,
            "user_username": t.user.tg_username if t.user else None,
            "category": t.category,
            "message": t.message,
            "screenshot_url": t.screenshot_url,
            "device_info": t.device_info,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "admin_reply": t.admin_reply,
            "created_at": t.created_at.strftime("%d.%m %H:%M") if t.created_at else "",
        })
    return {"status": "ok", "tickets": items}


class AdminTicketReplyRequest(BaseModel):
    reply: str
    status: str = "resolved"  # open, in_progress, resolved, closed


@router.post("/api/webapp/admin/support/tickets/{ticket_id}/reply")
async def webapp_admin_reply_support_ticket(
    ticket_id: str,
    payload: AdminTicketReplyRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Ответ на тикет из Superadmin Hub с отправкой в Telegram пользователю."""
    try:
        rep_uuid = uuid.UUID(ticket_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный ID тикета")

    ticket = await db.get(SupportTicket, rep_uuid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Тикет не найден")

    ticket.admin_reply = payload.reply.strip()
    if payload.status in ("open", "in_progress", "resolved", "closed"):
        ticket.status = TicketStatus(payload.status)
    if ticket.status in (TicketStatus.resolved, TicketStatus.closed):
        ticket.resolved_at = datetime.now(timezone.utc)
    ticket.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if payload.reply.strip():
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
                    f"{html.escape(payload.reply.strip())}\n\n"
                    f"Статус: <b>{st_text}</b>"
                )
                await bot.send_message(ticket.user_id, msg_text, parse_mode="HTML")
            finally:
                await bot.session.close()
        except Exception as send_err:
            logger.warning(f"Failed to send ticket reply to student {ticket.user_id}: {send_err}")

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
