"""
#3 Управление тегами интересов.
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import Optional

from web.dependencies import get_db, get_current_admin, check_csrf, generate_csrf_token
from database.models import InterestTag
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    error: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
):
    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = result.scalars().all()

    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/tags.html",
        {
            "request": request,
            "admin": admin,
            "tags": tags,
            "csrf_token": token_str,
            "error_msg": error,
            "success_msg": success,
        },
    )


@router.post("/tags/create", dependencies=[Depends(check_csrf)])
async def create_tag(
    request: Request,
    name: str = Form(...),
    emoji: str = Form(default="🏷"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    clean_name = name.strip()
    clean_emoji = emoji.strip() or "🏷"

    if not clean_name:
        return RedirectResponse("/admin/tags?error=Название+тега+не+может+быть+пустым", status_code=302)

    try:
        # Проверяем, существует ли уже такой тег
        existing = await db.scalar(select(InterestTag).where(InterestTag.name.ilike(clean_name)))
        if existing:
            existing.emoji = clean_emoji
            await db.commit()
            await log_admin_action(
                admin_id=admin.id,
                action="update_tag",
                details=f"Обновлен существующий тег #{existing.id} «{clean_name}» {clean_emoji}",
                db=db,
            )
            return RedirectResponse("/admin/tags?success=Тег+успешно+обновлен", status_code=302)

        tag = InterestTag(name=clean_name, emoji=clean_emoji)
        db.add(tag)
        await db.commit()
        await db.refresh(tag)

        await log_admin_action(
            admin_id=admin.id,
            action="create_tag",
            details=f"Создан новый тег #{tag.id} «{clean_name}» {clean_emoji}",
            db=db,
        )
        return RedirectResponse("/admin/tags?success=Тег+успешно+создан", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/tags?error=Ошибка+сохранения:+{str(e)[:50]}", status_code=302)


@router.post("/tags/{tag_id}/update", dependencies=[Depends(check_csrf)])
async def update_tag(
    tag_id: int,
    request: Request,
    name: str = Form(...),
    emoji: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    clean_name = name.strip()
    clean_emoji = emoji.strip() or "🏷"

    try:
        result = await db.execute(select(InterestTag).where(InterestTag.id == tag_id))
        tag = result.scalar_one_or_none()
        if tag:
            tag.name = clean_name
            tag.emoji = clean_emoji
            await db.commit()

            await log_admin_action(
                admin_id=admin.id,
                action="update_tag",
                details=f"Обновлен тег #{tag_id} -> «{clean_name}» {clean_emoji}",
                db=db,
            )
            return RedirectResponse("/admin/tags?success=Тег+сохранен", status_code=302)
        return RedirectResponse("/admin/tags?error=Тег+не+найден", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/tags?error=Ошибка+обновления:+{str(e)[:50]}", status_code=302)


@router.post("/tags/{tag_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_tag(
    tag_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(select(InterestTag).where(InterestTag.id == tag_id))
        tag = result.scalar_one_or_none()
        if tag:
            tag_name = tag.name
            await db.delete(tag)
            await db.commit()

            await log_admin_action(
                admin_id=admin.id,
                action="delete_tag",
                details=f"Удален тег #{tag_id} «{tag_name}»",
                db=db,
            )
            return RedirectResponse("/admin/tags?success=Тег+удален", status_code=302)
        return RedirectResponse("/admin/tags?error=Тег+не+найден", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/tags?error=Ошибка+удаления:+{str(e)[:50]}", status_code=302)
