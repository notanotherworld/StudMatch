"""
Авторизация модератора в веб-панели.
Защиты: rate limiting (Redis), Secure cookies, CSRF, logout через POST.
"""
import redis.asyncio as aioredis
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone

from bot.config import settings
from web.dependencies import get_db, verify_password, create_token, generate_csrf_token, check_csrf
from database.models import Admin

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

# ─── Redis для rate limiting ──────────────────────────────────
_redis: aioredis.Redis | None = None

def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 900  # 15 минут


async def _check_brute_force(login: str) -> None:
    """Поднимает HTTP 429 если превышен лимит попыток (#3)."""
    r = _get_redis()
    key = f"login_fail:admin:{login}"
    attempts = int(await r.get(key) or 0)
    if attempts >= MAX_ATTEMPTS:
        ttl = await r.ttl(key)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток. Повторите через {ttl // 60} мин.",
        )


async def _record_failure(login: str) -> None:
    r = _get_redis()
    key = f"login_fail:admin:{login}"
    await r.incr(key)
    await r.expire(key, LOCKOUT_SECONDS)


async def _clear_failures(login: str) -> None:
    await _get_redis().delete(f"login_fail:admin:{login}")


# ─── Страница логина ──────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login")
async def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Брутфорс-защита (#3)
    await _check_brute_force(login)

    result = await db.execute(select(Admin).where(Admin.login == login, Admin.is_active == True))
    admin = result.scalar_one_or_none()

    if not admin or not verify_password(password, admin.password_hash):
        await _record_failure(login)
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401,
        )

    # Успешный вход — сбрасываем счётчик
    await _clear_failures(login)

    # Обновляем last_login
    await db.execute(
        update(Admin).where(Admin.id == admin.id).values(last_login=datetime.now(timezone.utc))
    )
    await db.commit()

    token = create_token({"admin_id": admin.id, "role": admin.role.value})
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie(
        "admin_token", token,
        httponly=True,
        samesite="strict",   # строже "lax" (#5)
        secure=True,         # только HTTPS (#5)
        max_age=3600 * 8,
    )
    return response


# ─── Logout через POST (защита от CSRF-logout, #6) ────────────
@router.post("/logout", dependencies=[Depends(check_csrf)])
async def logout_post(request: Request):
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response


# Оставляем GET для обратной совместимости, но только удаляем куку без redirect-loop
@router.get("/logout")
async def logout_get():
    """Deprecated: используйте POST /admin/logout. GET оставлен для совместимости."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response


# ─── Смена пароля администратора ───────────────────────────────
from web.dependencies import get_current_admin, hash_password
from web.utils.audit import log_admin_action


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    admin=Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/change_password.html",
        {
            "request": request,
            "admin": admin,
            "error": None,
            "success": None,
            "csrf_token": getattr(request.state, "csrf_token", ""),
        },
    )


@router.post("/change-password", dependencies=[Depends(check_csrf)])
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(old_password, admin.password_hash):
        return templates.TemplateResponse(
            "admin/change_password.html",
            {
                "request": request,
                "admin": admin,
                "error": "Текущий пароль указан неверно.",
                "success": None,
                "csrf_token": getattr(request.state, "csrf_token", ""),
            },
            status_code=400,
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            "admin/change_password.html",
            {
                "request": request,
                "admin": admin,
                "error": "Новый пароль должен содержать не менее 8 символов.",
                "success": None,
                "csrf_token": getattr(request.state, "csrf_token", ""),
            },
            status_code=400,
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "admin/change_password.html",
            {
                "request": request,
                "admin": admin,
                "error": "Новый пароль и подтверждение не совпадают.",
                "success": None,
                "csrf_token": getattr(request.state, "csrf_token", ""),
            },
            status_code=400,
        )

    new_hash = hash_password(new_password)
    await db.execute(update(Admin).where(Admin.id == admin.id).values(password_hash=new_hash))
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="admin_password_change",
        target_type="admin", target_id=str(admin.id),
        details="Администратор изменил пароль учетной записи",
        ip_address=client_ip,
    )

    return templates.TemplateResponse(
        "admin/change_password.html",
        {
            "request": request,
            "admin": admin,
            "error": None,
            "success": "Пароль успешно изменён!",
            "csrf_token": getattr(request.state, "csrf_token", ""),
        },
    )
