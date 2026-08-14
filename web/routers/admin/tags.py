"""
#3 Управление тегами интересов.
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from web.dependencies import get_db, get_current_admin, check_csrf
from database.models import InterestTag

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = result.scalars().all()
    return templates.TemplateResponse(
        "admin/tags.html",
        {"request": request, "admin": admin, "tags": tags},
    )


@router.post("/tags/create", dependencies=[Depends(check_csrf)])
async def create_tag(
    name: str = Form(...),
    emoji: str = Form(default="🏷"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    tag = InterestTag(name=name.strip(), emoji=emoji.strip())
    db.add(tag)
    await db.commit()
    return RedirectResponse("/admin/tags", status_code=302)


@router.post("/tags/{tag_id}/update", dependencies=[Depends(check_csrf)])
async def update_tag(
    tag_id: int,
    name: str = Form(...),
    emoji: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(InterestTag)
        .where(InterestTag.id == tag_id)
        .values(name=name.strip(), emoji=emoji.strip())
    )
    await db.commit()
    return RedirectResponse("/admin/tags", status_code=302)


@router.post("/tags/{tag_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_tag(
    tag_id: int,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InterestTag).where(InterestTag.id == tag_id))
    tag = result.scalar_one_or_none()
    if tag:
        await db.delete(tag)
        await db.commit()
    return RedirectResponse("/admin/tags", status_code=302)
