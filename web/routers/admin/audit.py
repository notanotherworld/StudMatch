"""
Роутер журнала аудита действий администраторов.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from web.dependencies import get_db, get_current_admin
from database.models import AdminAuditLog

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/audit", response_class=HTMLResponse)
async def list_audit_logs(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    action: str = Query(default=""),
):
    per_page = 30
    offset = (page - 1) * per_page

    query = select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at))
    if action:
        query = query.where(AdminAuditLog.action.ilike(f"%{action}%"))

    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    logs = result.scalars().all()

    return templates.TemplateResponse(
        "admin/audit.html",
        {
            "request": request,
            "admin": admin,
            "logs": logs,
            "page": page,
            "action": action,
            "csrf_token": getattr(request.state, "csrf_token", ""),
        },
    )
