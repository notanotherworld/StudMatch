"""
Управление промокодами и реферальной программой в админ-панели.
"""
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, Query
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
    error: Optional[str] = Query(default=None),
    success: Optional[str] = Query(default=None),
):
    promos = []
    top_ambassadors = []
    total_promos = 0
    total_activations = 0
    total_referrals = 0

    try:
        # Список промокодов
        result = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
        promos = list(result.scalars().all())
        total_promos = len(promos)
        total_activations = sum(p.activations_count for p in promos)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error loading promo codes: {e}", exc_info=True)

    try:
        # Топ амбассадоров (реферальная программа)
        ref_res = await db.execute(
            select(
                User.referrer_id,
                func.count(User.id).label("ref_count"),
            )
            .where(User.referrer_id.isnot(None))
            .group_by(User.referrer_id)
            .order_by(desc("ref_count"))
            .limit(10)
        )
        top_refs_raw = ref_res.all()

        for inviter_id, count in top_refs_raw:
            if not inviter_id:
                continue
            u_res = await db.execute(
                select(User).options(selectinload(User.profile)).where(User.id == inviter_id)
            )
            inviter = u_res.scalar_one_or_none()
            username = inviter.tg_username if inviter else None
            name = inviter.profile.name if inviter and inviter.profile and inviter.profile.name else None
            top_ambassadors.append({
                "user_id": inviter_id,
                "username": username,
                "name": name,
                "count": count,
            })

        total_referrals_res = await db.execute(
            select(func.count(User.id)).where(User.referrer_id.isnot(None))
        )
        total_referrals = total_referrals_res.scalar_one() or 0
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error loading ambassadors: {e}", exc_info=True)

    from web.dependencies import generate_csrf_token
    token_str = generate_csrf_token(request.cookies.get("admin_token", ""))

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
            "csrf_token": token_str,
            "error_msg": error,
            "success_msg": success,
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
    if not norm_code:
        return RedirectResponse("/admin/promos?error=Код+промокода+не+может+быть+пустым", status_code=302)

    expires_dt = None
    if expires_at_str.strip():
        try:
            expires_dt = datetime.strptime(expires_at_str.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Проверяем на дубликат
    existing = await db.execute(select(PromoCode).where(PromoCode.code == norm_code))
    if existing.scalar_one_or_none():
        return RedirectResponse("/admin/promos?error=Промокод+с+таким+именем+уже+существует", status_code=302)

    try:
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

        return RedirectResponse("/admin/promos?success=Промокод+успешно+создан", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/promos?error=Ошибка+создания:+{str(e)[:50]}", status_code=302)


@router.post("/promos/{promo_id}/toggle", dependencies=[Depends(check_csrf)])
async def toggle_promo(
    promo_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
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
            return RedirectResponse("/admin/promos?success=Статус+промокода+обновлен", status_code=302)
        return RedirectResponse("/admin/promos?error=Промокод+не+найден", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/promos?error=Ошибка:+{str(e)[:50]}", status_code=302)


@router.post("/promos/{promo_id}/delete", dependencies=[Depends(check_csrf)])
async def delete_promo(
    promo_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
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
            return RedirectResponse("/admin/promos?success=Промокод+удален", status_code=302)
        return RedirectResponse("/admin/promos?error=Промокод+не+найден", status_code=302)
    except Exception as e:
        await db.rollback()
        return RedirectResponse(f"/admin/promos?error=Ошибка+удаления:+{str(e)[:50]}", status_code=302)
