"""
Сервис активации промокодов с защитой от повторного использования и атомарным начислением.
"""
from typing import Tuple, Optional
from datetime import datetime, timezone, timedelta
import logging
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import PromoCode, PromoActivation, User, Profile

logger = logging.getLogger(__name__)


async def activate_promo_code(
    db: AsyncSession,
    user_id: int,
    code_text: str,
) -> Tuple[bool, str]:
    """
    Активация промокода для пользователя.
    Возвращает (успех: bool, сообщение: str).
    """
    try:
        normalized_code = code_text.strip().upper()
        if not normalized_code:
            return False, "⚠️ Укажите промокод."

        # Ищем промокод
        result = await db.execute(select(PromoCode).where(PromoCode.code == normalized_code))
        promo = result.scalar_one_or_none()
        if not promo or not promo.is_active:
            return False, "❌ Промокод не найден или отключён."

        # Проверяем срок действия
        now = datetime.now(timezone.utc)
        if promo.expires_at:
            exp = promo.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                return False, "⌛ Срок действия этого промокода истёк."

        # Проверяем лимит активаций
        if promo.max_activations > 0 and promo.activations_count >= promo.max_activations:
            return False, "🚫 Лимит активаций этого промокода исчерпан."

        # Проверяем, не активировал ли уже этот пользователь
        act_res = await db.execute(
            select(PromoActivation).where(
                and_(PromoActivation.user_id == user_id, PromoActivation.promo_id == promo.id)
            )
        )
        if act_res.scalar_one_or_none():
            return False, "ℹ️ Вы уже активировали этот промокод ранее."

        # Загружаем пользователя
        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return False, "Пользователь не найден."

        reward_msg = ""
        # Начисляем награду
        if promo.reward_type == "superlikes":
            current_balance = user.superlike_balance or 0
            new_balance = current_balance + promo.reward_value
            await db.execute(
                update(User).where(User.id == user_id).values(superlike_balance=new_balance)
            )
            reward_msg = f"⭐️ +{promo.reward_value} Суперлайков (Баланс: {new_balance})"

        elif promo.reward_type == "boost":
            hours = 24 * promo.reward_value
            base_time = user.boost_until if user.boost_until and user.boost_until > now else now
            if base_time.tzinfo is None:
                base_time = base_time.replace(tzinfo=timezone.utc)
            new_boost = base_time + timedelta(hours=hours)
            await db.execute(
                update(User).where(User.id == user_id).values(boost_until=new_boost)
            )
            reward_msg = f"⚡️ Буст анкеты на {hours}ч активирован!"

        elif promo.reward_type == "rating":
            prof_res = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = prof_res.scalar_one_or_none()
            if profile:
                current_score = profile.rating_score or 0.0
                new_score = current_score + float(promo.reward_value)
                await db.execute(
                    update(Profile).where(Profile.user_id == user_id).values(rating_score=new_score)
                )
                reward_msg = f"🏆 +{promo.reward_value} баллов рейтинга (Текущий: {new_score:.0f})"
            else:
                reward_msg = f"🏆 +{promo.reward_value} баллов рейтинга!"
        else:
            reward_msg = "🎁 Бонус получен!"

        # Фиксируем активацию
        activation = PromoActivation(promo_id=promo.id, user_id=user_id)
        db.add(activation)

        # Инкрементируем счетчик активаций промокода
        await db.execute(
            update(PromoCode)
            .where(PromoCode.id == promo.id)
            .values(activations_count=promo.activations_count + 1)
        )
        await db.commit()

        return True, f"🎉 <b>Промокод «{promo.code}» успешно активирован!</b>\n\nВам начислено: <b>{reward_msg}</b>"

    except Exception as e:
        logger.error(f"Error activating promo code '{code_text}' for user {user_id}: {e}", exc_info=True)
        await db.rollback()
        return False, "⚠️ Произошла ошибка при активации промокода. Попробуйте позже."
