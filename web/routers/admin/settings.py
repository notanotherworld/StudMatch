"""
Управление системными настройками платформы и Feature Flags в админ-панели.
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from web.dependencies import get_db, get_current_admin, check_csrf, generate_csrf_token
from database.models import SystemSetting
from bot.utils.dynamic_settings import (
    get_system_setting,
    set_system_setting,
    get_payment_products_catalog,
    save_payment_products_catalog,
)
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

    products_catalog = await get_payment_products_catalog()

    smtp_info = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "from_email": settings.SMTP_FROM,
        "is_configured": bool(settings.SMTP_USER and settings.SMTP_PASSWORD),
    }

    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "admin": admin,
            "cfg": settings_map,
            "products_catalog": products_catalog,
            "smtp": smtp_info,
            "saved": saved == "1",
            "csrf_token": token_str,
        },
    )


@router.post("/settings/products/add", dependencies=[Depends(check_csrf)])
async def add_custom_product(
    request: Request,
    name: str = Form(...),
    emoji: str = Form(default="🎁"),
    price: int = Form(...),
    bonus_type: str = Form(default="custom"),
    bonus_value: int = Form(default=1),
    description: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Добавить новый тариф / дополнительную услугу в каталог."""
    import re
    clean_name = name.strip()
    clean_emoji = emoji.strip() or "🎁"
    clean_desc = description.strip()
    clean_price = max(1, int(price))

    if not clean_name:
        return RedirectResponse("/admin/settings?error=Укажите+название+услуги", status_code=302)

    # Генерируем уникальный slug-идентификатор
    try:
        import transliterate
        slug = transliterate.translit(clean_name, 'ru', reversed=True)
    except Exception:
        slug = clean_name
    slug = re.sub(r'[^a-zA-Z0-9_]+', '_', slug.lower()).strip('_')
    if not slug:
        slug = f"service_{int(datetime.now().timestamp())}"
    slug = f"custom_{slug[:25]}"

    catalog = await get_payment_products_catalog()
    # Проверяем нет ли уже с таким id
    if any(p.get("id") == slug for p in catalog):
        slug = f"{slug}_{int(datetime.now().timestamp()) % 10000}"

    new_item = {
        "id": slug,
        "name": clean_name,
        "emoji": clean_emoji,
        "price": clean_price,
        "bonus_type": bonus_type,
        "bonus_value": max(1, int(bonus_value)),
        "description": clean_desc,
        "is_active": True,
        "is_default": False,
    }
    catalog.append(new_item)
    await save_payment_products_catalog(catalog)

    await log_admin_action(
        db=db,
        admin=admin,
        action="add_payment_product",
        target_type="payment_product",
        target_id=slug,
        details=f"Создан новый тариф/услуга «{clean_emoji} {clean_name}» за {clean_price} ₽ (тип: {bonus_type}, бонус: {bonus_value})",
    )

    return RedirectResponse("/admin/settings?saved=1", status_code=302)


@router.post("/settings/products/{product_id}/toggle", dependencies=[Depends(check_csrf)])
async def toggle_product_active(
    product_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Включение / отключение услуги в каталоге."""
    catalog = await get_payment_products_catalog()
    target_name = product_id
    for item in catalog:
        if item.get("id") == product_id:
            item["is_active"] = not item.get("is_active", True)
            target_name = item.get("name", product_id)
            break

    await save_payment_products_catalog(catalog)
    await log_admin_action(
        db=db,
        admin=admin,
        action="toggle_payment_product",
        target_type="payment_product",
        target_id=product_id,
        details=f"Переключен статус активности тарифа '{target_name}'",
    )
    return RedirectResponse("/admin/settings?saved=1", status_code=302)


@router.post("/settings/products/{product_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_custom_product(
    product_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Удаление кастомной услуги из каталога."""
    catalog = await get_payment_products_catalog()
    catalog = [p for p in catalog if p.get("id") != product_id]
    await save_payment_products_catalog(catalog)

    await log_admin_action(
        db=db,
        admin=admin,
        action="delete_payment_product",
        target_type="payment_product",
        target_id=product_id,
        details=f"Удален тариф/услуга '{product_id}'",
    )
    return RedirectResponse("/admin/settings?saved=1", status_code=302)


@router.post("/settings", dependencies=[Depends(check_csrf)])
async def save_settings(
    request: Request,
    maintenance_mode: str = Form(default="false"),
    maintenance_message: str = Form(default=""),
    referral_reward_superlikes: str = Form(default="3"),
    require_email_verification: str = Form(default="true"),
    reward_score_gpa: str = Form(default="20"),
    reward_score_olympiad: str = Form(default="50"),
    reward_score_competition: str = Form(default="40"),
    reward_score_participation: str = Form(default="15"),
    auto_update_broadcast_enabled: str = Form(default="false"),
    update_broadcast_text: str = Form(default=""),
    emergency_mode: str = Form(default="false"),
    freeze_registrations: str = Form(default="false"),
    anti_flood_strict: str = Form(default="false"),
    emergency_message: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    from bot.services.update_broadcast import UPDATE_TEXT
    from datetime import datetime

    # Считываем все отправленные цены на товары
    form_data = await request.form()
    catalog = await get_payment_products_catalog()
    for item in catalog:
        pid = item.get("id")
        # Проверяем поле вида product_price_{pid} или price_{pid}
        field_name = f"product_price_{pid}"
        if field_name in form_data:
            try:
                item["price"] = max(1, int(form_data[field_name]))
            except Exception:
                pass
        elif f"price_{pid}" in form_data:
            try:
                item["price"] = max(1, int(form_data[f"price_{pid}"]))
            except Exception:
                pass

    await save_payment_products_catalog(catalog)

    updates = {
        "maintenance_mode": "true" if maintenance_mode == "true" else "false",
        "maintenance_message": maintenance_message.strip(),
        "emergency_mode": "true" if emergency_mode == "true" else "false",
        "freeze_registrations": "true" if freeze_registrations == "true" else "false",
        "anti_flood_strict": "true" if anti_flood_strict == "true" else "false",
        "emergency_message": emergency_message.strip() or "🚨 <b>Сервер временно недоступен</b>\n\nВключён режим защиты от перегрузки. Доступ будет восстановлен в ближайшее время!",
        "referral_reward_superlikes": referral_reward_superlikes.strip(),
        "require_email_verification": "true" if require_email_verification == "true" else "false",
        "reward_score_gpa": reward_score_gpa.strip(),
        "reward_score_olympiad": reward_score_olympiad.strip(),
        "reward_score_competition": reward_score_competition.strip(),
        "reward_score_participation": reward_score_participation.strip(),
        "auto_update_broadcast_enabled": "true" if auto_update_broadcast_enabled == "true" else "false",
        "update_broadcast_text": update_broadcast_text.strip() or UPDATE_TEXT,
    }

    for k, v in updates.items():
        await set_system_setting(k, v)

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db=db,
        admin=admin,
        action="update_system_settings",
        target_type="system",
        target_id="settings",
        details="Обновлены системные настройки и цены тарифов",
        ip_address=client_ip,
    )

    return RedirectResponse("/admin/settings?saved=1", status_code=302)


@router.post("/emergency/quick-toggle")
async def quick_toggle_emergency(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Быстрое переключение экстренных режимов защиты в 1 клик через AJAX."""
    from fastapi.responses import JSONResponse
    try:
        body = await request.json()
        key = body.get("key")
        value = "true" if str(body.get("value")).lower() in ("true", "1", "yes") else "false"

        allowed_keys = {"emergency_mode", "freeze_registrations", "anti_flood_strict", "maintenance_mode"}
        if key not in allowed_keys:
            return JSONResponse({"success": False, "error": "Недопустимый ключ настройки"}, status_code=400)

        await set_system_setting(key, value)

        client_ip = request.client.host if request.client else None
        await log_admin_action(
            db, admin, action="emergency_toggle", target_type="security", target_id=key,
            details=f"Экстренное переключение режима {key} -> {value}",
            ip_address=client_ip,
        )

        return JSONResponse({"success": True, "key": key, "value": value})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/emergency/status")
async def get_emergency_status(
    admin=Depends(get_current_admin),
):
    """Получение текущего статуса всех защитных механизмов."""
    from fastapi.responses import JSONResponse
    from bot.utils.dynamic_settings import get_system_setting

    status = {
        "emergency_mode": await get_system_setting("emergency_mode", "false"),
        "freeze_registrations": await get_system_setting("freeze_registrations", "false"),
        "anti_flood_strict": await get_system_setting("anti_flood_strict", "false"),
        "maintenance_mode": await get_system_setting("maintenance_mode", "false"),
    }
    return JSONResponse({"success": True, "status": status})


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
