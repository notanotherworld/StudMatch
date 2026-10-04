"""
Управление внутренней экономикой («Зачёты» 🎓), каталогом магазина и транзакциями.
"""
from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, ShopItem, EconomyTransaction
from database.crud import (
    get_user,
    get_shop_catalog,
    get_shop_item,
    add_user_credits,
    spend_user_credits,
)
from web.dependencies import get_db, get_current_admin, check_csrf
from web.utils.audit import log_admin_action

logger = logging.getLogger(__name__)
router = Router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/economy", response_class=HTMLResponse)
async def economy_dashboard_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    user_search: Optional[int] = Query(default=None),
    tx_type_filter: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
):
    """Главная страница управления экономикой и магазином."""
    # 1. Товары магазина
    items = await get_shop_catalog(db, only_active=False)

    # 2. Агрегированные метрики экономики
    total_credits_res = await db.execute(select(func.sum(User.credits_balance)))
    total_credits_in_circulation = total_credits_res.scalar_one_or_none() or 0

    active_streaks_res = await db.execute(
        select(func.count(User.id)).where(User.streak_days > 0)
    )
    active_streaks_count = active_streaks_res.scalar_one_or_none() or 0

    earned_credits_res = await db.execute(
        select(func.sum(EconomyTransaction.amount)).where(EconomyTransaction.amount > 0)
    )
    total_earned = earned_credits_res.scalar_one_or_none() or 0

    spent_credits_res = await db.execute(
        select(func.sum(EconomyTransaction.amount)).where(EconomyTransaction.amount < 0)
    )
    total_spent = abs(spent_credits_res.scalar_one_or_none() or 0)

    # 3. Транзакции
    tx_query = select(EconomyTransaction).order_by(desc(EconomyTransaction.created_at)).limit(50)
    if user_search:
        tx_query = tx_query.where(EconomyTransaction.user_id == user_search)
    if tx_type_filter:
        tx_query = tx_query.where(EconomyTransaction.tx_type == tx_type_filter)

    tx_res = await db.execute(tx_query)
    transactions = list(tx_res.scalars().all())

    return templates.TemplateResponse(
        "admin/economy.html",
        {
            "request": request,
            "admin": admin,
            "items": items,
            "total_credits": total_credits_in_circulation,
            "active_streaks": active_streaks_count,
            "total_earned": total_earned,
            "total_spent": total_spent,
            "transactions": transactions,
            "user_search": user_search,
            "tx_type_filter": tx_type_filter,
            "success": success,
            "error": error,
        },
    )


@router.post("/economy/items/add", dependencies=[Depends(check_csrf)])
async def add_shop_item_endpoint(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    code: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    category: str = Form("consumable"),
    price_credits: int = Form(0),
    price_rub: Optional[str] = Form(None),
    icon: str = Form("🛍"),
    bonus_type: Optional[str] = Form(None),
    bonus_value: int = Form(1),
    duration_days: Optional[str] = Form(None),
    sort_order: int = Form(0),
):
    """Добавление нового товара в каталог."""
    await check_csrf(request)

    clean_code = code.strip().lower()
    existing = await get_shop_item(db, clean_code)
    if existing:
        return RedirectResponse("/admin/economy?error=Товар+с+таким+кодом+уже+существует", status_code=303)

    parsed_price_rub = int(price_rub.strip()) if price_rub and price_rub.strip().isdigit() else None
    parsed_duration = int(duration_days.strip()) if duration_days and duration_days.strip().isdigit() else None

    new_item = ShopItem(
        code=clean_code,
        title=title.strip(),
        description=description.strip() if description else None,
        category=category.strip(),
        price_credits=max(0, price_credits),
        price_rub=parsed_price_rub,
        icon=icon.strip() or "🛍",
        bonus_type=bonus_type.strip() if bonus_type else None,
        bonus_value=max(1, bonus_value),
        duration_days=parsed_duration,
        is_active=True,
        sort_order=sort_order,
    )
    db.add(new_item)
    await db.commit()

    await log_admin_action(
        db,
        admin=admin,
        action="add_shop_item",
        target_type="shop_item",
        target_id=clean_code,
        details=f"Добавлен товар {title} ({price_credits} 🎓)",
    )

    return RedirectResponse("/admin/economy?success=Товар+успешно+добавлен", status_code=303)


@router.post("/economy/items/edit", dependencies=[Depends(check_csrf)])
async def edit_shop_item_endpoint(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    item_id: int = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    category: str = Form("consumable"),
    price_credits: int = Form(0),
    price_rub: Optional[str] = Form(None),
    icon: str = Form("🛍"),
    bonus_type: Optional[str] = Form(None),
    bonus_value: int = Form(1),
    duration_days: Optional[str] = Form(None),
    sort_order: int = Form(0),
    is_active: Optional[str] = Form(None),
):
    """Редактирование параметров существующего товара."""
    res = await db.execute(select(ShopItem).where(ShopItem.id == item_id))
    item = res.scalar_one_or_none()
    if not item:
        return RedirectResponse("/admin/economy?error=Товар+не+найден", status_code=303)

    parsed_price_rub = int(price_rub.strip()) if price_rub and price_rub.strip().isdigit() else None
    parsed_duration = int(duration_days.strip()) if duration_days and duration_days.strip().isdigit() else None

    item.title = title.strip()
    item.description = description.strip() if description else None
    item.category = category.strip()
    item.price_credits = max(0, price_credits)
    item.price_rub = parsed_price_rub
    item.icon = icon.strip() or "🛍"
    item.bonus_type = bonus_type.strip() if bonus_type else None
    item.bonus_value = max(1, bonus_value)
    item.duration_days = parsed_duration
    item.sort_order = sort_order
    item.is_active = is_active in ("true", "1", "on", "yes", True)

    await db.commit()

    await log_admin_action(
        db,
        admin=admin,
        action="edit_shop_item",
        target_type="shop_item",
        target_id=item.code,
        details=f"Обновлен товар {title} ({price_credits} 🎓)",
    )

    return RedirectResponse("/admin/economy?success=Товар+успешно+обновлён", status_code=303)


@router.post("/economy/items/toggle", dependencies=[Depends(check_csrf)])
async def toggle_shop_item_endpoint(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    item_id: int = Form(...),
):
    """Быстрое переключение активности товара."""
    res = await db.execute(select(ShopItem).where(ShopItem.id == item_id))
    item = res.scalar_one_or_none()
    if not item:
        return RedirectResponse("/admin/economy?error=Товар+не+найден", status_code=303)

    item.is_active = not item.is_active
    await db.commit()

    return RedirectResponse("/admin/economy?success=Статус+товара+изменён", status_code=303)


@router.post("/economy/users/adjust", dependencies=[Depends(check_csrf)])
async def adjust_user_credits_endpoint(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    user_id: int = Form(...),
    amount: int = Form(...),
    reason: str = Form("Корректировка администратором"),
):
    """Ручное начисление или списание «Зачётов» студента администратором."""

    user = await get_user(db, user_id)
    if not user:
        return RedirectResponse("/admin/economy?error=Студент+не+найден", status_code=303)

    if amount > 0:
        new_bal = await add_user_credits(
            db,
            user_id=user_id,
            amount=amount,
            tx_type="admin",
            description=f"Админ {admin.login}: {reason}",
            reference_id=f"admin_{admin.id}",
        )
        act = f"Начислено +{amount} 🎓"
    elif amount < 0:
        success, new_bal = await spend_user_credits(
            db,
            user_id=user_id,
            amount=abs(amount),
            tx_type="admin",
            description=f"Админ {admin.login}: {reason}",
            reference_id=f"admin_{admin.id}",
        )
        if not success:
            return RedirectResponse("/admin/economy?error=Недостаточно+средств+для+списания", status_code=303)
        act = f"Списано {amount} 🎓"
    else:
        return RedirectResponse("/admin/economy", status_code=303)

    await log_admin_action(
        db,
        admin=admin,
        action="adjust_credits",
        target_type="user",
        target_id=str(user_id),
        details=f"{act}. Причина: {reason}. Новый баланс: {new_bal} 🎓",
    )

    return RedirectResponse(f"/admin/economy?success=Баланс+пользователя+{user_id}+обновлён", status_code=303)
