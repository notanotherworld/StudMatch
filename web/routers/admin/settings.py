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
    from bot.config import settings
    result = await db.execute(select(SystemSetting))
    all_settings_list = result.scalars().all()
    settings_map = {s.key: s.value for s in all_settings_list}

    smtp_info = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "from_email": settings.SMTP_FROM,
        "is_configured": bool(settings.SMTP_USER and settings.SMTP_PASSWORD),
    }

    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "admin": admin,
            "cfg": settings_map,
            "smtp": smtp_info,
            "saved": saved == "1",
        },
    )


@router.post("/settings", dependencies=[Depends(check_csrf)])
async def save_settings(
    request: Request,
    maintenance_mode: str = Form(default="false"),
    maintenance_message: str = Form(default=""),
    price_premium_1m: str = Form(default="199"),
    price_boost_24h: str = Form(default="99"),
    price_superlike_3: str = Form(default="49"),
    price_superlike_10: str = Form(default="199"),
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
        "price_premium_1m": price_premium_1m.strip(),
        "price_boost_24h": price_boost_24h.strip(),
        "price_superlike_3": price_superlike_3.strip(),
        "price_superlike_10": price_superlike_10.strip(),
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


@router.post("/settings/test-email", dependencies=[Depends(check_csrf)])
async def test_email_action(
    request: Request,
    target_email: str = Form(...),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Тестовая отправка письма для проверки настроек SMTP."""
    from bot.utils.email import send_test_email
    from fastapi.responses import JSONResponse

    clean_email = target_email.strip()
    if not clean_email or "@" not in clean_email:
        return JSONResponse({"success": False, "error": "Некорректный адрес email"})

    res = await send_test_email(clean_email)
    
    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="test_smtp_email", target_type="system", target_id="smtp",
        details=f"Тест SMTP на {clean_email}: success={res.get('success')}",
        ip_address=client_ip,
    )

    return JSONResponse(res)
