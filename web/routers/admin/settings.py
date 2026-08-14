"""
Управление системными настройками платформы и Feature Flags в админ-панели.
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from web.dependencies import get_db, get_current_admin, check_csrf
from database.models import SystemSetting
from bot.utils.dynamic_settings import get_system_setting, set_system_setting
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    saved: str = "",
):
    result = await db.execute(select(SystemSetting))
    all_settings_list = result.scalars().all()
    settings_map = {s.key: s.value for s in all_settings_list}

    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "admin": admin,
            "cfg": settings_map,
            "saved": saved == "1",
        },
    )


@router.post("/settings", dependencies=[Depends(check_csrf)])
async def save_settings(
    request: Request,
    maintenance_mode: str = Form(default="false"),
    maintenance_message: str = Form(default=""),
    price_superlike_3: str = Form(default="99"),
    price_superlike_10: str = Form(default="249"),
    price_boost_24h: str = Form(default="149"),
    referral_reward_superlikes: str = Form(default="3"),
    require_email_verification: str = Form(default="true"),
    reward_score_gpa: str = Form(default="20"),
    reward_score_olympiad: str = Form(default="50"),
    reward_score_competition: str = Form(default="40"),
    reward_score_participation: str = Form(default="15"),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    updates = {
        "maintenance_mode": "true" if maintenance_mode == "true" else "false",
        "maintenance_message": maintenance_message.strip(),
        "price_superlike_3": price_superlike_3.strip(),
        "price_superlike_10": price_superlike_10.strip(),
        "price_boost_24h": price_boost_24h.strip(),
        "referral_reward_superlikes": referral_reward_superlikes.strip(),
        "require_email_verification": "true" if require_email_verification == "true" else "false",
        "reward_score_gpa": reward_score_gpa.strip(),
        "reward_score_olympiad": reward_score_olympiad.strip(),
        "reward_score_competition": reward_score_competition.strip(),
        "reward_score_participation": reward_score_participation.strip(),
    }

    for k, v in updates.items():
        await set_system_setting(k, v)

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="update_system_settings", target_type="system", target_id="settings",
        details=f"Обновлены настройки платформы (Maintenance: {updates['maintenance_mode']}, EmailReq: {updates['require_email_verification']})",
        ip_address=client_ip,
    )

    return RedirectResponse("/admin/settings?saved=1", status_code=302)
