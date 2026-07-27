"""Управление университетами."""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from web.dependencies import get_db, get_current_admin
from database.models import University

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/universities", response_class=HTMLResponse)
async def list_universities(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(University).order_by(University.id))
    universities = result.scalars().all()
    return templates.TemplateResponse(
        "admin/universities.html",
        {"request": request, "admin": admin, "universities": universities},
    )


@router.post("/universities/create")
async def create_university(
    name: str = Form(...),
    short_name: str = Form(...),
    email_domains: str = Form(...),
    city: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    uni = University(name=name, short_name=short_name, email_domains=email_domains, city=city)
    db.add(uni)
    await db.commit()
    return RedirectResponse("/admin/universities", status_code=302)


@router.post("/universities/{uni_id}/toggle")
async def toggle_university(
    uni_id: int,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(University).where(University.id == uni_id))
    uni = result.scalar_one_or_none()
    if uni:
        await db.execute(update(University).where(University.id == uni_id).values(is_active=not uni.is_active))
        await db.commit()
    return RedirectResponse("/admin/universities", status_code=302)
