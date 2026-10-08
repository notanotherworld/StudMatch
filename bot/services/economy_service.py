"""
Сервис внутренней экономики, наград и магазина платформы StudMatch.
"""
import logging
from typing import Optional, Tuple
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, EconomyTransaction
from database.crud import (
    add_user_credits,
    get_user,
    get_user_credits_balance,
)

logger = logging.getLogger(__name__)


def format_credits(amount: int) -> str:
    """Склонение слова 'зачёт'."""
    abs_amt = abs(amount)
    if 11 <= abs_amt % 100 <= 19:
        unit = "зачётов"
    else:
        rem = abs_amt % 10
        if rem == 1:
            unit = "зачёт"
        elif 2 <= rem <= 4:
            unit = "зачёта"
        else:
            unit = "зачётов"
    return f"{amount} 🎓 {unit}"


def get_frame_title(frame_code: Optional[str]) -> Optional[str]:
    """Возвращает название и бейдж рамки профиля."""
    frames_map = {
        "frame_gold": "🥇 «Отличник»",
        "frame_headman": "👔 «Староста»",
        "frame_neon": "🌌 «Неон»",
        "frame_fire": "🔥 «Пламя стрика»",
    }
    return frames_map.get(frame_code) if frame_code else None


async def has_received_reward(
    db: AsyncSession,
    user_id: int,
    reference_id: str,
) -> bool:
    """Проверяет, получал ли пользователь уже эту разовую награду."""
    res = await db.execute(
        select(EconomyTransaction.id).where(
            and_(
                EconomyTransaction.user_id == user_id,
                EconomyTransaction.reference_id == reference_id,
            )
        )
    )
    return res.scalar_one_or_none() is not None


from sqlalchemy.exc import IntegrityError

async def reward_email_verification(db: AsyncSession, user_id: int) -> Tuple[bool, int]:
    """Награда за подтверждение университетского email (+40 🎓, x3 для Премиум: +120 🎓)."""
    ref_id = "onboarding_email_verified"
    
    # Атомарная блокировка пользователя во избежание race condition (H4)
    res = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = res.scalar_one_or_none()
    if not user:
        return False, 0

    if await has_received_reward(db, user_id, ref_id) or await has_received_reward(db, user_id, "perm_quest_onboarding_email"):
        return False, 0

    is_prem = bool(user.is_premium)
    mult = 3 if is_prem else 1
    amount = 40 * mult
    prem_suffix = " (👑 Премиум x3)" if is_prem else ""

    try:
        new_bal = await add_user_credits(
            db,
            user_id=user_id,
            amount=amount,
            tx_type="onboarding",
            description=f"Подтверждение университетской почты{prem_suffix}",
            reference_id=ref_id,
        )
        return True, new_bal
    except IntegrityError:
        await db.rollback()
        return False, 0


async def reward_profile_completion(db: AsyncSession, user_id: int) -> Tuple[bool, int]:
    """Награда за полное заполнение анкеты (+20 🎓, x3 для Премиум: +60 🎓)."""
    ref_id = "onboarding_profile_complete"

    # Атомарная блокировка пользователя во избежание race condition (H4)
    res = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = res.scalar_one_or_none()
    if not user:
        return False, 0

    if await has_received_reward(db, user_id, ref_id) or await has_received_reward(db, user_id, "perm_quest_onboarding_profile"):
        return False, 0

    is_prem = bool(user.is_premium)
    mult = 3 if is_prem else 1
    amount = 20 * mult
    prem_suffix = " (👑 Премиум x3)" if is_prem else ""

    try:
        new_bal = await add_user_credits(
            db,
            user_id=user_id,
            amount=amount,
            tx_type="onboarding",
            description=f"Заполнение всех разделов анкеты{prem_suffix}",
            reference_id=ref_id,
        )
        return True, new_bal
    except IntegrityError:
        await db.rollback()
        return False, 0


async def reward_gallery_upload(db: AsyncSession, user_id: int) -> Tuple[bool, int]:
    """Награда за добавление от 3 фото в профиль (+12 🎓, x3 для Премиум: +36 🎓)."""
    ref_id = "onboarding_gallery_3_photos"

    # Атомарная блокировка пользователя во избежание race condition (H4)
    res = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = res.scalar_one_or_none()
    if not user:
        return False, 0

    if await has_received_reward(db, user_id, ref_id) or await has_received_reward(db, user_id, "perm_quest_onboarding_gallery"):
        return False, 0

    is_prem = bool(user.is_premium)
    mult = 3 if is_prem else 1
    amount = 12 * mult
    prem_suffix = " (👑 Премиум x3)" if is_prem else ""

    try:
        new_bal = await add_user_credits(
            db,
            user_id=user_id,
            amount=amount,
            tx_type="onboarding",
            description=f"Загрузка от 3-х фотографий в портфолио{prem_suffix}",
            reference_id=ref_id,
        )
        return True, new_bal
    except IntegrityError:
        await db.rollback()
        return False, 0


async def reward_achievement_approved(db: AsyncSession, user_id: int, achievement_id: int) -> Tuple[bool, int]:
    """Награда за подтверждённый модератором диплом/олимпиаду (+75 🎓)."""
    ref_id = f"achievement_{achievement_id}"

    # Атомарная блокировка пользователя во избежание race condition (H4)
    res = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = res.scalar_one_or_none()
    if not user:
        return False, 0

    if await has_received_reward(db, user_id, ref_id):
        return False, 0

    try:
        new_bal = await add_user_credits(
            db,
            user_id=user_id,
            amount=75,
            tx_type="onboarding",
            description="Подтверждение академического достижения / диплома",
            reference_id=ref_id,
        )
        return True, new_bal
    except IntegrityError:
        await db.rollback()
        return False, 0


async def reward_referral(db: AsyncSession, referrer_id: int, new_user_id: int) -> bool:
    """
    Награда за приглашённого студента:
    Рефереру +50 🎓, приглашённому другу +30 🎓.
    """
    ref_key = f"referral_{new_user_id}"

    # Атомарная блокировка реферера во избежание race condition (H4)
    res = await db.execute(select(User).where(User.id == referrer_id).with_for_update())
    referrer = res.scalar_one_or_none()
    if not referrer:
        return False

    if await has_received_reward(db, referrer_id, ref_key):
        return False

    try:
        # Начисляем пригласившему
        await add_user_credits(
            db,
            user_id=referrer_id,
            amount=50,
            tx_type="referral",
            description=f"Приглашение друга (ID {new_user_id})",
            reference_id=ref_key,
        )
        # Начисляем другу
        await add_user_credits(
            db,
            user_id=new_user_id,
            amount=30,
            tx_type="referral",
            description="Бонус за регистрацию по приглашению друга",
            reference_id=f"referred_by_{referrer_id}",
        )
        return True
    except IntegrityError:
        await db.rollback()
        return False
