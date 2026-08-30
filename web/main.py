"""
FastAPI приложение: admin panel + HR cabinet + YooKassa webhook.
Защиты: CSRF context processor, security headers, OpenAPI отключён в prod.
"""
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from web.routers.admin import (
    auth as admin_auth, dashboard, users, documents, ratings,
    payments as admin_payments, tariffs as admin_tariffs, employers, universities,
    broadcast, tags, reports, health, audit, promos, settings as admin_settings,
    consents, fake_users,
)
from web.routers.employer import (
    auth as employer_auth,
    dashboard as employer_dashboard,
    profiles as employer_profiles,
    requests as employer_requests,
    settings as employer_settings,
)
from web.dependencies import generate_csrf_token


import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Синхронизируем схему базы данных (добавление новых колонок)
    from database.session import engine
    from database.migrations import ensure_database_schema
    await ensure_database_schema(engine)
    yield


# OpenAPI только в dev (не в prod) — убираем /docs из production (#12)
import os
_DEBUG = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(
    title="СтудМэч Admin",
    lifespan=lifespan,
    docs_url="/docs" if _DEBUG else None,    # /docs только в DEBUG-режиме
    redoc_url="/redoc" if _DEBUG else None,  # /redoc только в DEBUG-режиме
)

# ─── Security Headers middleware (#15) ───────────────────────
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ─── CORS Middleware ───────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
from bot.config import settings

origins = [settings.DOMAIN]
if _DEBUG:
    origins.extend(["http://localhost:8000", "http://127.0.0.1:8000"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ─── CSRF context processor ────────────────────────────────
# Добавляем csrf_token в каждый Jinja2-контекст
# Это позволяет base.html использовать csrf_token в meta-теге
templates = Jinja2Templates(directory="web/templates")

@app.middleware("http")
async def inject_csrf_into_templates(request: Request, call_next):
    """Добавляем csrf_token в request.state для использования в шаблонах."""
    token_cookie = request.cookies.get("admin_token") or request.cookies.get("employer_token") or ""
    request.state.csrf_token = generate_csrf_token(token_cookie) if token_cookie else ""
    response = await call_next(request)
    return response

# Обработчик ошибок для предотвращения белого экрана
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.exception_handlers import http_exception_handler

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    # Если зависимость вернула редирект (302 на /admin/login)
    if exc.status_code in (301, 302, 303, 307, 308) and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)

    if exc.status_code == 403 and "Invalid CSRF token" in str(exc.detail):
        referer = request.headers.get("referer") or "/admin/dashboard"
        sep = "&" if "?" in referer else "?"
        return RedirectResponse(f"{referer}{sep}error=Сессия+обновлена,+повторите+действие", status_code=302)

    return await http_exception_handler(request, exc)

# Статика
app.mount("/static", StaticFiles(directory="web/static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("web/static/img/logo.jpg")

app.include_router(admin_auth.router, prefix="/admin", tags=["Admin Auth"])
app.include_router(dashboard.router, prefix="/admin", tags=["Dashboard"])
app.include_router(fake_users.router, prefix="/admin", tags=["Fake Users"])
app.include_router(users.router, prefix="/admin", tags=["Users"])
app.include_router(documents.router, prefix="/admin", tags=["Documents"])
app.include_router(ratings.router, prefix="/admin", tags=["Ratings"])
app.include_router(admin_payments.router, prefix="/admin", tags=["Payments"])
app.include_router(admin_tariffs.router, prefix="/admin", tags=["Tariffs"])
app.include_router(employers.router, prefix="/admin", tags=["Employers"])
app.include_router(universities.router, prefix="/admin", tags=["Universities"])
app.include_router(broadcast.router, prefix="/admin", tags=["Broadcast"])
app.include_router(tags.router, prefix="/admin", tags=["Tags"])
app.include_router(reports.router, prefix="/admin", tags=["Reports"])
app.include_router(health.router, prefix="/admin", tags=["Health"])
app.include_router(audit.router, prefix="/admin", tags=["Audit"])
app.include_router(promos.router, prefix="/admin", tags=["Promos"])
app.include_router(admin_settings.router, prefix="/admin", tags=["Settings"])
app.include_router(consents.router, prefix="/admin", tags=["Consents"])

# Роутеры — Кабинет HR / Работодателя
app.include_router(employer_auth.router, prefix="/employer", tags=["Employer Auth"])
app.include_router(employer_dashboard.router, prefix="/employer", tags=["Employer Dashboard"])
app.include_router(employer_profiles.router, prefix="/employer", tags=["Employer Profiles"])
app.include_router(employer_requests.router, prefix="/employer", tags=["Employer Requests"])
app.include_router(employer_settings.router, prefix="/employer", tags=["Employer Settings"])
