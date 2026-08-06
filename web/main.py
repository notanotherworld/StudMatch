"""
FastAPI приложение: admin panel + HR cabinet + YooKassa webhook.
Защиты: CSRF context processor, security headers, OpenAPI отключён в prod.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from web.routers.admin import (
    auth as admin_auth, dashboard, users, documents, ratings,
    payments as admin_payments, employers, universities,
    broadcast, tags, reports,
)
from web.routers.employer import auth as employer_auth, profiles as employer_profiles
from web.dependencies import generate_csrf_token


@asynccontextmanager
async def lifespan(app: FastAPI):
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

# Статика
app.mount("/static", StaticFiles(directory="web/static"), name="static")

app.include_router(admin_auth.router, prefix="/admin", tags=["Admin Auth"])
app.include_router(dashboard.router, prefix="/admin", tags=["Dashboard"])
app.include_router(users.router, prefix="/admin", tags=["Users"])
app.include_router(documents.router, prefix="/admin", tags=["Documents"])
app.include_router(ratings.router, prefix="/admin", tags=["Ratings"])
app.include_router(admin_payments.router, prefix="/admin", tags=["Payments"])
app.include_router(employers.router, prefix="/admin", tags=["Employers"])
app.include_router(universities.router, prefix="/admin", tags=["Universities"])
app.include_router(broadcast.router, prefix="/admin", tags=["Broadcast"])
app.include_router(tags.router, prefix="/admin", tags=["Tags"])
app.include_router(reports.router, prefix="/admin", tags=["Reports"])

# Роутеры — Кабинет HR
app.include_router(employer_auth.router, prefix="/employer", tags=["Employer Auth"])
app.include_router(employer_profiles.router, prefix="/employer", tags=["Employer Profiles"])
