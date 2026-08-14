"""
Общие утилиты для Web: аутентификация сессий (JWT), зависимости FastAPI.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
import jwt
import bcrypt
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import settings
from database.session import AsyncSessionLocal
from database.models import Admin, AdminRole, Employer

SECRET = settings.SECRET_KEY
ALGORITHM = "HS256"
SESSION_TTL_HOURS = 8

# ─── CSRF ────────────────────────────────────────────────────
# Используем itsdangerous (уже в requirements.txt) для HMAC-токенов
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_csrf_signer = URLSafeTimedSerializer(SECRET, salt="csrf")


def generate_csrf_token(session_id: str) -> str:
    """Генерируем CSRF-токен привязанный к сессии."""
    return _csrf_signer.dumps(session_id)


def verify_csrf_token(token: str, session_id: str, max_age: int = 86400) -> bool:
    """Проверяем CSRF-токен (TTL 24 часа)."""
    try:
        value = _csrf_signer.loads(token, max_age=max_age)
        if value == session_id:
            return True
        # Если exact match не прошёл, сверяем id пользователя из JWT-токенов
        p1 = decode_token(value) if value else None
        p2 = decode_token(session_id) if session_id else None
        if p1 and p2:
            if p1.get("admin_id") and p1.get("admin_id") == p2.get("admin_id"):
                return True
            if p1.get("employer_id") and p1.get("employer_id") == p2.get("employer_id"):
                return True
        return False
    except (BadSignature, SignatureExpired, Exception):
        return False


async def check_csrf(request: Request) -> None:
    """Зависимость FastAPI: проверяет CSRF-токен для POST-запросов."""
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return

    # Берём токен из заголовка или формы
    token = request.headers.get("X-CSRF-Token")
    if not token:
        try:
            form = await request.form()
            token = form.get("csrf_token", "")
        except Exception:
            token = ""

    session_id = request.cookies.get("admin_token") or request.cookies.get("employer_token") or ""

    if not token or not session_id or not verify_csrf_token(token, session_id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(payload: dict, hours: int = SESSION_TTL_HOURS) -> str:
    data = payload.copy()
    data["exp"] = datetime.now(timezone.utc) + timedelta(hours=hours)
    return jwt.encode(data, SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# ─── Зависимость: текущий модератор ──────────────────────────
async def get_current_admin(request: Request, db: AsyncSession = Depends(get_db)) -> Admin:
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

    payload = decode_token(token)
    if not payload or "admin_id" not in payload:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

    result = await db.execute(select(Admin).where(Admin.id == payload["admin_id"]))
    admin = result.scalar_one_or_none()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

    return admin


require_admin = get_current_admin


# ─── Зависимость: только суперадмин (#4 RBAC) ────────────────
async def require_superadmin(admin: Admin = Depends(get_current_admin)) -> Admin:
    """Разрешает доступ только администраторам с ролью superadmin."""
    if admin.role != AdminRole.superadmin:
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещён: требуется роль superadmin",
        )
    return admin


# ─── Зависимость: текущий работодатель ───────────────────────
async def get_current_employer(request: Request, db: AsyncSession = Depends(get_db)) -> Employer:
    token = request.cookies.get("employer_token")
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/employer/login"})

    payload = decode_token(token)
    if not payload or "employer_id" not in payload:
        raise HTTPException(status_code=302, headers={"Location": "/employer/login"})

    result = await db.execute(select(Employer).where(Employer.id == payload["employer_id"]))
    employer = result.scalar_one_or_none()
    if not employer or not employer.is_active:
        raise HTTPException(status_code=302, headers={"Location": "/employer/login"})

    return employer
