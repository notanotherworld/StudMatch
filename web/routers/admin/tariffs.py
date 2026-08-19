"""
Управление тарифами, услугами и ценами (ЮКасса).
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime
import re

from web.dependencies import get_db, get_current_admin, check_csrf, generate_csrf_token
from database.models import Payment, PaymentStatus
from bot.utils.dynamic_settings import (
    get_payment_products_catalog,
    save_payment_products_catalog,
    set_system_setting,
)
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/tariffs", response_class=HTMLResponse)
async def tariffs_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    error: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
):
    catalog = await get_payment_products_catalog()

    # Считаем агрегированную статистику по каждому тарифу из БД
    stats_result = await db.execute(
        select(Payment.product, func.count(Payment.id), func.sum(Payment.amount_rub))
        .where(Payment.status == PaymentStatus.succeeded)
        .group_by(Payment.product)
    )
    sales_map = {}
    total_sales_count = 0
    total_sales_revenue = 0.0

    for row in stats_result.all():
        prod_val = row[0].value if hasattr(row[0], 'value') else str(row[0])
        cnt = row[1]
        rev = float(row[2] or 0)
        sales_map[prod_val] = {"count": cnt, "revenue": rev}
        total_sales_count += cnt
        total_sales_revenue += rev

    # Прикрепляем статистику к каждому элементу каталога
    for item in catalog:
        pid = item.get("id")
        meta_sales = sales_map.get(pid, {"count": 0, "revenue": 0.0})
        item["sales_count"] = meta_sales["count"]
        item["sales_revenue"] = meta_sales["revenue"]

    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

    return templates.TemplateResponse(
        "admin/tariffs.html",
        {
            "request": request,
            "admin": admin,
            "catalog": catalog,
            "total_sales_count": total_sales_count,
            "total_sales_revenue": total_sales_revenue,
            "csrf_token": token_str,
            "error_msg": error,
            "success_msg": success,
        },
    )


@router.post("/tariffs/save-prices", dependencies=[Depends(check_csrf)])
async def save_all_tariff_prices(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Массовое сохранение цен всех тарифов."""
    form_data = await request.form()
    catalog = await get_payment_products_catalog()

    changed_items = []
    for item in catalog:
        pid = item.get("id")
        field_name = f"price_{pid}"
        if field_name in form_data:
            try:
                new_price = max(1, int(form_data[field_name]))
                if new_price != item.get("price"):
                    old_price = item.get("price")
                    item["price"] = new_price
                    changed_items.append(f"{item.get('name')}: {old_price} ₽ -> {new_price} ₽")
            except Exception:
                pass

    await save_payment_products_catalog(catalog)

    await log_admin_action(
        db=db,
        admin=admin,
        action="update_tariff_prices",
        target_type="tariffs",
        target_id="catalog",
        details="Обновлены цены тарифов: " + (", ".join(changed_items) if changed_items else "без изменений"),
    )

    return RedirectResponse("/admin/tariffs?success=Цены+тарифов+успешно+сохранены+и+обновлены", status_code=302)


@router.post("/tariffs/update-single")
async def update_single_price_ajax(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Мгновенное AJAX сохранение цены отдельного тарифа."""
    try:
        body = await request.json()
        product_id = body.get("product_id")
        price = int(body.get("price", 0))

        if not product_id or price <= 0:
            return JSONResponse({"success": False, "error": "Некорректная цена"}, status_code=400)

        catalog = await get_payment_products_catalog()
        found = False
        target_name = product_id
        for item in catalog:
            if item.get("id") == product_id:
                item["price"] = price
                target_name = item.get("name", product_id)
                found = True
                break

        if not found:
            return JSONResponse({"success": False, "error": "Тариф не найден"}, status_code=404)

        await save_payment_products_catalog(catalog)

        await log_admin_action(
            db=db,
            admin=admin,
            action="update_single_tariff_price",
            target_type="tariff",
            target_id=product_id,
            details=f"Изменена цена тарифа '{target_name}' на {price} ₽",
        )

        return JSONResponse({"success": True, "product_id": product_id, "price": price})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/tariffs/add", dependencies=[Depends(check_csrf)])
async def add_tariff(
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
    """Создать новый тариф или услугу."""
    clean_name = name.strip()
    clean_emoji = emoji.strip() or "🎁"
    clean_desc = description.strip()
    clean_price = max(1, int(price))

    if not clean_name:
        return RedirectResponse("/admin/tariffs?error=Укажите+название+услуги", status_code=302)

    import transliterate
    try:
        slug = transliterate.translit(clean_name, 'ru', reversed=True)
    except Exception:
        slug = clean_name
    slug = re.sub(r'[^a-zA-Z0-9_]+', '_', slug.lower()).strip('_')
    if not slug:
        slug = f"service_{int(datetime.now().timestamp())}"
    slug = f"custom_{slug[:25]}"

    catalog = await get_payment_products_catalog()
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
        action="add_tariff",
        target_type="tariff",
        target_id=slug,
        details=f"Создан тариф «{clean_emoji} {clean_name}» ({clean_price} ₽, тип: {bonus_type}, бонус: {bonus_value})",
    )

    return RedirectResponse("/admin/tariffs?success=Новый+тариф+успешно+создан", status_code=302)


@router.post("/tariffs/{product_id}/toggle", dependencies=[Depends(check_csrf)])
async def toggle_tariff(
    product_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
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
        action="toggle_tariff",
        target_type="tariff",
        target_id=product_id,
        details=f"Переключен статус активности тарифа '{target_name}'",
    )
    return RedirectResponse("/admin/tariffs?success=Статус+тарифа+обновлён", status_code=302)


@router.post("/tariffs/{product_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_tariff(
    product_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    catalog = await get_payment_products_catalog()
    catalog = [p for p in catalog if p.get("id") != product_id]
    await save_payment_products_catalog(catalog)

    await log_admin_action(
        db=db,
        admin=admin,
        action="delete_tariff",
        target_type="tariff",
        target_id=product_id,
        details=f"Удален тариф '{product_id}'",
    )
    return RedirectResponse("/admin/tariffs?success=Тариф+успешно+удалён", status_code=302)
