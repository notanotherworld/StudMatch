"""
Авторизация работодателя/HR.
Защиты: rate limiting (Redis), Secure cookies, CSRF, logout через POST.
"""
import redis.asyncio as aioredis
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import settings
from web.dependencies import get_db, verify_password, create_token, check_csrf
from database.models import Employer

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
    key = f"login_fail:employer:{login}"
    attempts = int(await r.get(key) or 0)
    if attempts >= MAX_ATTEMPTS:
        ttl = await r.ttl(key)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток. Повторите через {ttl // 60} мин.",
        )


async def _record_failure(login: str) -> None:
    r = _get_redis()
    key = f"login_fail:employer:{login}"
    await r.incr(key)
    await r.expire(key, LOCKOUT_SECONDS)


async def _clear_failures(login: str) -> None:
    await _get_redis().delete(f"login_fail:employer:{login}")


# ─── Страница логина ──────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("employer/login.html", {"request": request, "error": None})


@router.post("/login")
async def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Брутфорс-защита (#3)
    await _check_brute_force(login)

    result = await db.execute(
        select(Employer).where(Employer.login == login, Employer.is_active == True)
    )
    employer = result.scalar_one_or_none()

    if not employer or not verify_password(password, employer.password_hash):
        await _record_failure(login)
        return templates.TemplateResponse(
            "employer/login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401,
        )

    await _clear_failures(login)

    token = create_token({"employer_id": employer.id})
    response = RedirectResponse(url="/employer/profiles", status_code=302)
    response.set_cookie(
        "employer_token", token,
        httponly=True,
        samesite="strict",   # строже "lax" (#5)
        secure=True,         # только HTTPS (#5)
        max_age=3600 * 8,
    )
    return response


# ─── Logout через POST (#6) ───────────────────────────────────
@router.post("/logout", dependencies=[Depends(check_csrf)])
async def logout_post(request: Request):
    response = RedirectResponse(url="/employer/login", status_code=302)
    response.delete_cookie("employer_token")
    return response


@router.get("/logout")
async def logout_get():
    """Deprecated: используйте POST /employer/logout."""
    response = RedirectResponse(url="/employer/login", status_code=302)
    response.delete_cookie("employer_token")
    return response
