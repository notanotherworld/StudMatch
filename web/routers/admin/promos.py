"""
Управление промокодами и реферальной программой в админ-панели.
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, desc
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import uuid

from web.dependencies import get_db, get_current_admin, check_csrf
from database.models import PromoCode, PromoActivation, User
from web.utils.audit import log_admin_action

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/promos", response_class=HTMLResponse)
async def promos_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # Список промокодов
    result = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
    promos = result.scalars().all()

    # Топ амбассадоров (реферальная программа)
    ref_res = await db.execute(
        select(
            User.referred_by,
            func.count(User.id).label("ref_count"),
        )
        .where(User.referred_by.isnot(None))
        .group_by(User.referred_by)
        .order_by(desc("ref_count"))
        .limit(10)
    )
    top_refs_raw = ref_res.all()

    top_ambassadors = []
    for inviter_id, count in top_refs_raw:
        u_res = await db.execute(
            select(User).options(selectinload(User.profile)).where(User.id == inviter_id)
        )
        inviter = u_res.scalar_one_or_none()
        name = inviter.profile.name if inviter and inviter.profile and inviter.profile.name else None
        top_ambassadors.append({
            "user_id": inviter_id,
            "username": inviter.tg_username if inviter else None,
            "name": name,
            "count": count,
        })

    # Общая статистика
    total_promos = len(promos)
    total_activations = sum(p.activations_count for p in promos)
    total_referrals_res = await db.execute(
        select(func.count(User.id)).where(User.referred_by.isnot(None))
    )
    total_referrals = total_referrals_res.scalar_one() or 0

    return templates.TemplateResponse(
        "admin/promos.html",
        {
            "request": request,
            "admin": admin,
            "promos": promos,
            "top_ambassadors": top_ambassadors,
            "total_promos": total_promos,
            "total_activations": total_activations,
            "total_referrals": total_referrals,
        },
    )


@router.post("/promos/create", dependencies=[Depends(check_csrf)])
async def create_promo(
    request: Request,
    code: str = Form(...),
    reward_type: str = Form(...),
    reward_value: int = Form(...),
    max_activations: int = Form(default=0),
    expires_at_str: str = Form(default=""),
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    norm_code = code.strip().upper()
    expires_dt = None
    if expires_at_str.strip():
        try:
            expires_dt = datetime.strptime(expires_at_str.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Проверяем на дубликат
    existing = await db.execute(select(PromoCode).where(PromoCode.code == norm_code))
    if existing.scalar_one_or_none():
        return RedirectResponse("/admin/promos", status_code=302)

    promo = PromoCode(
        code=norm_code,
        reward_type=reward_type,
        reward_value=max(1, reward_value),
        max_activations=max(0, max_activations),
        expires_at=expires_dt,
        is_active=True,
    )
    db.add(promo)
    await db.commit()

    client_ip = request.client.host if request.client else None
    await log_admin_action(
        db, admin, action="create_promo", target_type="promo", target_id=norm_code,
        details=f"Создан промокод {norm_code}: {reward_type} (+{reward_value}), лимит: {max_activations}",
        ip_address=client_ip,
    )

    return RedirectResponse("/admin/promos", status_code=302)


@router.post("/promos/{promo_id}/toggle", dependencies=[Depends(check_csrf)])
async def toggle_promo(
    promo_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    p_uuid = uuid.UUID(promo_id)
    res = await db.execute(select(PromoCode).where(PromoCode.id == p_uuid))
    promo = res.scalar_one_or_none()
    if promo:
        new_status = not promo.is_active
        await db.execute(update(PromoCode).where(PromoCode.id == p_uuid).values(is_active=new_status))
        await db.commit()

        client_ip = request.client.host if request.client else None
        await log_admin_action(
            db, admin, action="toggle_promo", target_type="promo", target_id=promo.code,
            details=f"Статус промокода {promo.code} изменён на: {'Активен' if new_status else 'Отключён'}",
            ip_address=client_ip,
        )

    return RedirectResponse("/admin/promos", status_code=302)


@router.post("/promos/{promo_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_promo(
    promo_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    p_uuid = uuid.UUID(promo_id)
    res = await db.execute(select(PromoCode).where(PromoCode.id == p_uuid))
    promo = res.scalar_one_or_none()
    if promo:
        code_name = promo.code
        await db.delete(promo)
        await db.commit()

        client_ip = request.client.host if request.client else None
        await log_admin_action(
            db, admin, action="delete_promo", target_type="promo", target_id=code_name,
            details=f"Удалён промокод {code_name}",
            ip_address=client_ip,
        )

    return RedirectResponse("/admin/promos", status_code=302)
