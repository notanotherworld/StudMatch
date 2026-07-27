"""
FastAPI приложение: admin panel + HR cabinet + YooKassa webhook.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from web.routers.admin import (
    auth as admin_auth, dashboard, users, documents, ratings,
    payments as admin_payments, employers, universities,
    broadcast, tags, reports,
)
from web.routers.employer import auth as employer_auth, profiles as employer_profiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация при старте
    yield


app = FastAPI(title="СтудМэч Admin", lifespan=lifespan)

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
