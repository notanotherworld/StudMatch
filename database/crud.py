"""
CRUD-операции для основных сущностей.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.orm import selectinload
import random
import string

from database.models import (
    User, Profile, University, EmailToken, Achievement,
    Swipe, Match, Admin, Employer, EmployerProfileAccess, Payment,
    VerifiedStatus, SwipeAction, ModeEnum, PaymentStatus, PaymentProduct,
)


# ─────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────
async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.profile), selectinload(User.university))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_user(db: AsyncSession, user_id: int, tg_username: Optional[str] = None) -> User:
    user = await get_user(db, user_id)
    if not user:
        user = User(id=user_id, tg_username=tg_username)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif tg_username and user.tg_username != tg_username:
        user.tg_username = tg_username
        await db.commit()
    return user


async def set_user_consent(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(consent_given=True, consent_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def set_user_mode(db: AsyncSession, user_id: int, mode: ModeEnum) -> None:
    await db.execute(update(User).where(User.id == user_id).values(mode=mode))
    await db.commit()


async def deduct_superlike(db: AsyncSession, user_id: int) -> bool:
    """Списать 1 суперлайк. Возвращает False если баланс 0."""
    user = await get_user(db, user_id)
    if not user or user.superlike_balance <= 0:
        return False
    await db.execute(
        update(User).where(User.id == user_id).values(superlike_balance=User.superlike_balance - 1)
    )
    await db.commit()
    return True


async def add_superlikes(db: AsyncSession, user_id: int, amount: int) -> None:
    await db.execute(
        update(User).where(User.id == user_id).values(superlike_balance=User.superlike_balance + amount)
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────
# Universities
# ─────────────────────────────────────────────────────────────
async def get_active_universities(db: AsyncSession) -> List[University]:
    result = await db.execute(select(University).where(University.is_active == True))
    return list(result.scalars().all())


async def find_university_by_email(db: AsyncSession, email: str) -> Optional[University]:
    """Найти вуз по домену email."""
    domain = "@" + email.split("@")[-1].lower()
    result = await db.execute(select(University).where(University.is_active == True))
    universities = result.scalars().all()
    for uni in universities:
        domains = [d.strip().lower() for d in uni.email_domains.split(",")]
        if domain in domains:
            return uni
    return None


# ─────────────────────────────────────────────────────────────
# Email Tokens
# ─────────────────────────────────────────────────────────────
async def create_email_token(db: AsyncSession, user_id: int) -> str:
    """Создать 6-значный код верификации (TTL 15 минут)."""
    token = "".join(random.choices(string.digits, k=6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    # Инвалидируем старые токены
    await db.execute(update(EmailToken).where(EmailToken.user_id == user_id).values(used=True))

    db.add(EmailToken(user_id=user_id, token=token, expires_at=expires_at))
    await db.commit()
    return token


async def verify_email_token(db: AsyncSession, user_id: int, token: str) -> bool:
    """Проверить код. Возвращает True если верный и не истёк."""
    result = await db.execute(
        select(EmailToken).where(
            and_(
                EmailToken.user_id == user_id,
                EmailToken.token == token,
                EmailToken.used == False,
                EmailToken.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    email_token = result.scalar_one_or_none()
    if not email_token:
        return False

    email_token.used = True
    await db.execute(update(User).where(User.id == user_id).values(email_verified=True))
    await db.commit()
    return True


# ─────────────────────────────────────────────────────────────
# Profiles
# ─────────────────────────────────────────────────────────────
async def get_or_create_profile(db: AsyncSession, user_id: int) -> Profile:
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


async def update_profile(db: AsyncSession, user_id: int, **kwargs) -> Profile:
    await db.execute(update(Profile).where(Profile.user_id == user_id).values(**kwargs))
    await db.commit()
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    return result.scalar_one()


async def get_top_profiles(
    db: AsyncSession,
    viewer_id: int,
    mode: ModeEnum,
    limit: int = 6,
) -> List[Profile]:
    """
    Получить топ-6 студентов для свайпа.
    Исключаем: самого пользователя, уже свайпнутых, забаненных.
    Сортировка: буст → рейтинг.
    """
    # ID уже свайпнутых
    swiped_result = await db.execute(
        select(Swipe.to_user_id).where(Swipe.from_user_id == viewer_id)
    )
    swiped_ids = {row[0] for row in swiped_result.all()}
    swiped_ids.add(viewer_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Profile)
        .options(selectinload(Profile.user))
        .join(User, Profile.user_id == User.id)
        .where(
            and_(
                Profile.is_visible == True,
                Profile.is_complete == True,
                User.is_active == True,
                User.email_verified == True,
                ~Profile.user_id.in_(swiped_ids),
            )
        )
        .order_by(
            (User.boost_until > now).desc(),
            Profile.rating_score.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────
# Swipes & Matches
# ─────────────────────────────────────────────────────────────
async def create_swipe(
    db: AsyncSession, from_id: int, to_id: int, action: SwipeAction, comment: Optional[str] = None
) -> bool:
    """
    Сохранить свайп. Возвращает True если это взаимный лайк (мэтч).
    """
    # Проверяем, не было ли уже свайпа
    existing = await db.execute(
        select(Swipe).where(and_(Swipe.from_user_id == from_id, Swipe.to_user_id == to_id))
    )
    if existing.scalar_one_or_none():
        return False

    db.add(Swipe(from_user_id=from_id, to_user_id=to_id, action=action, comment=comment))
    await db.commit()

    # Проверяем взаимный лайк
    if action in (SwipeAction.like, SwipeAction.superlike):
        reverse = await db.execute(
            select(Swipe).where(
                and_(
                    Swipe.from_user_id == to_id,
                    Swipe.to_user_id == from_id,
                    Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
                )
            )
        )
        if reverse.scalar_one_or_none():
            # Получаем режим от просматривающего
            user = await get_user(db, from_id)
            db.add(Match(user1_id=from_id, user2_id=to_id, mode=user.mode))
            await db.commit()
            return True
    return False


# ─────────────────────────────────────────────────────────────
# Achievements
# ─────────────────────────────────────────────────────────────
ACHIEVEMENT_SCORES = {
    "case_participant": 25.0,
    "place_3": 50.0,
    "place_2": 75.0,
    "place_1": 100.0,
    "volunteer": 20.0,
    "internship": 60.0,
    "forum_attender": 15.0,
    "forum_speaker": 40.0,
    # Fallback/compatibility
    "gpa": 10.0,
    "competition": 15.0,
    "case": 25.0,
    "olympiad": 20.0,
    "diploma": 30.0,
    "publication": 20.0,
    "participation": 5.0,
}


async def approve_achievement(db: AsyncSession, achievement_id, admin_id: int) -> None:
    """Подтвердить достижение и начислить очки к рейтингу."""
    result = await db.execute(select(Achievement).where(Achievement.id == achievement_id))
    achievement = result.scalar_one_or_none()
    if not achievement:
        return

    score = ACHIEVEMENT_SCORES.get(achievement.type.value, 5.0)
    achievement.verified = VerifiedStatus.approved
    achievement.verified_by = admin_id
    achievement.verified_at = datetime.now(timezone.utc)
    achievement.score = score

    # Пересчитываем рейтинг профиля
    all_approved = await db.execute(
        select(func.sum(Achievement.score)).where(
            and_(Achievement.user_id == achievement.user_id, Achievement.verified == VerifiedStatus.approved)
        )
    )
    total_score = all_approved.scalar() or 0.0

    await db.execute(
        update(Profile).where(Profile.user_id == achievement.user_id).values(rating_score=total_score)
    )
    await db.commit()


async def reject_achievement(
    db: AsyncSession, achievement_id, admin_id: int, reason: str
) -> None:
    await db.execute(
        update(Achievement)
        .where(Achievement.id == achievement_id)
        .values(
            verified=VerifiedStatus.rejected,
            verified_by=admin_id,
            reject_reason=reason,
            verified_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────────────────────
async def create_payment(
    db: AsyncSession, user_id: int, product: PaymentProduct, amount_rub: float
) -> Payment:
    payment = Payment(user_id=user_id, product=product, amount_rub=amount_rub)
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


async def confirm_payment(db: AsyncSession, yookassa_payment_id: str) -> Optional[Payment]:
    """Подтвердить платёж и начислить товар."""
    result = await db.execute(
        select(Payment).where(Payment.yookassa_payment_id == yookassa_payment_id)
    )
    payment = result.scalar_one_or_none()
    if not payment or payment.status != PaymentStatus.pending:
        return None

    payment.status = PaymentStatus.succeeded
    payment.updated_at = datetime.now(timezone.utc)

    # Начисляем товар
    if payment.product == PaymentProduct.superlike_3:
        await add_superlikes(db, payment.user_id, 3)
    elif payment.product == PaymentProduct.superlike_5:
        await add_superlikes(db, payment.user_id, 5)
    elif payment.product in (PaymentProduct.superlike_1, PaymentProduct.superlike_10):
        await add_superlikes(db, payment.user_id, 3)
    elif payment.product == PaymentProduct.premium_1m:
        boost_until = datetime.now(timezone.utc) + timedelta(days=30)
        await add_superlikes(db, payment.user_id, 10)
        await db.execute(
            update(User).where(User.id == payment.user_id).values(boost_until=boost_until)
        )

    await db.commit()
    return payment


# ─────────────────────────────────────────────────────────────
# Employer Access
# ─────────────────────────────────────────────────────────────
async def get_employer_profiles(
    db: AsyncSession, employer_id: int
) -> List[EmployerProfileAccess]:
    result = await db.execute(
        select(EmployerProfileAccess)
        .options(selectinload(EmployerProfileAccess.profile))
        .where(EmployerProfileAccess.employer_id == employer_id)
        .order_by(EmployerProfileAccess.granted_at.desc())
    )
    return list(result.scalars().all())


async def mark_profile_viewed(db: AsyncSession, access_id) -> None:
    await db.execute(
        update(EmployerProfileAccess)
        .where(EmployerProfileAccess.id == access_id)
        .values(viewed_at=datetime.now(timezone.utc))
    )
    await db.commit()
