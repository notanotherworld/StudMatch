"""
CRUD-операции для основных сущностей.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, func, case
from sqlalchemy.orm import selectinload
import random
import string
import logging

logger = logging.getLogger(__name__)

from database.models import (
    User, Profile, University, EmailToken, Achievement,
    Swipe, Match, Admin, Employer, EmployerProfileAccess, Payment, Report,
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
    """Списать 1 суперлайк. Возвращает False если баланс 0. Атомарная операция."""
    result = await db.execute(
        update(User)
        .where(and_(User.id == user_id, User.superlike_balance > 0))
        .values(superlike_balance=User.superlike_balance - 1)
        .returning(User.superlike_balance)
    )
    await db.commit()
    return result.scalar_one_or_none() is not None


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
    """Найти вуз по домену email. Фильтрация через SQL LIKE."""
    domain = "@" + email.split("@")[-1].lower()
    result = await db.execute(
        select(University).where(
            and_(
                University.is_active == True,
                University.email_domains.ilike(f"%{domain}%"),
            )
        )
    )
    universities = result.scalars().all()
    # Точная проверка домена (ILIKE может дать ложные совпадения при похожих доменах)
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
async def get_profile(db: AsyncSession, user_id: int) -> Optional[Profile]:
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    return result.scalar_one_or_none()


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
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=user_id, **kwargs)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile

    for key, value in kwargs.items():
        if hasattr(profile, key):
            setattr(profile, key, value)

    await db.commit()
    await db.refresh(profile)
    return profile


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
    # ID уже свайпнутых и тех, на кого отправлена жалоба
    swiped_result = await db.execute(
        select(Swipe.to_user_id).where(Swipe.from_user_id == viewer_id)
    )
    swiped_ids = {row[0] for row in swiped_result.all()}

    reported_result = await db.execute(
        select(Report.reported_id).where(Report.reporter_id == viewer_id)
    )
    for row in reported_result.all():
        swiped_ids.add(row[0])

    swiped_ids.add(viewer_id)

    now = datetime.now(timezone.utc)
    is_complete_cond = (
        Profile.career_is_complete == True
        if mode == ModeEnum.career
        else Profile.is_complete == True
    )

    result = await db.execute(
        select(Profile)
        .options(selectinload(Profile.user))
        .join(User, Profile.user_id == User.id)
        .where(
            and_(
                Profile.is_visible == True,
                is_complete_cond,
                User.is_active == True,
                User.email_verified == True,
                ~Profile.user_id.in_(swiped_ids),
            )
        )
        .order_by(
            (User.premium_until > now).desc(),
            (User.boost_until > now).desc(),
            User.email_verified.desc(),
            Profile.rating_score.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_next_profile(
    db: AsyncSession,
    viewer_id: int,
    mode: Optional[ModeEnum] = None,
) -> Optional[Profile]:
    """
    Получить следующую не свайпнутую анкету для поочерёдного свайпа (1 за раз).
    Исключаем: самого пользователя, уже свайпнутых, тех на кого отправлена жалоба, забаненных.
    Сортировка: буст → рейтинг.
    """
    swiped_result = await db.execute(
        select(Swipe.to_user_id).where(Swipe.from_user_id == viewer_id)
    )
    swiped_ids = {row[0] for row in swiped_result.all()}

    reported_result = await db.execute(
        select(Report.reported_id).where(Report.reporter_id == viewer_id)
    )
    for row in reported_result.all():
        swiped_ids.add(row[0])

    swiped_ids.add(viewer_id)

    now = datetime.now(timezone.utc)

    # Загружаем профиль смотрящего для фильтрации
    viewer_profile = await get_profile(db, viewer_id)

    # Фильтры для режима Знакомств (гендер)
    gender_filters = []
    if mode == ModeEnum.dating and viewer_profile:
        # 1. Пол кандидата должен совпадать с тем, кого ищет viewer
        if viewer_profile.target_gender == "female":
            gender_filters.append(or_(Profile.gender == "female", Profile.gender.is_(None)))
        elif viewer_profile.target_gender == "male":
            gender_filters.append(or_(Profile.gender == "male", Profile.gender.is_(None)))

        # 2. Кандидат должен быть согласен на пол viewer'а (или искать Всех/любого)
        if viewer_profile.gender == "male":
            gender_filters.append(
                or_(
                    Profile.target_gender == "male",
                    Profile.target_gender == "all",
                    Profile.target_gender.is_(None),
                )
            )
        elif viewer_profile.gender == "female":
            gender_filters.append(
                or_(
                    Profile.target_gender == "female",
                    Profile.target_gender == "all",
                    Profile.target_gender.is_(None),
                )
            )

    # Фильтры поиска (возраст, курс, факультет)
    search_filters = []
    if viewer_profile:
        # 1. Фильтр по возрасту (если возраст указан)
        min_a = viewer_profile.filter_min_age
        max_a = viewer_profile.filter_max_age
        if min_a and max_a:
            search_filters.append(
                or_(
                    Profile.age.is_(None),
                    and_(Profile.age >= min_a, Profile.age <= max_a)
                )
            )

        # 2. Фильтр по курсу
        min_y = viewer_profile.filter_min_year
        max_y = viewer_profile.filter_max_year
        if min_y and max_y:
            search_filters.append(
                or_(
                    Profile.year.is_(None),
                    and_(Profile.year >= min_y, Profile.year <= max_y)
                )
            )

        # 3. Фильтр по специальности / факультету
        f_major = viewer_profile.filter_major
        if f_major and f_major != "all":
            search_filters.append(
                or_(
                    Profile.major.is_(None),
                    Profile.major.ilike(f"%{f_major}%")
                )
            )

    is_complete_cond = (
        Profile.career_is_complete == True
        if mode == ModeEnum.career
        else Profile.is_complete == True
    )

    incoming_action = (
        select(Swipe.action)
        .where(
            Swipe.from_user_id == Profile.user_id,
            Swipe.to_user_id == viewer_id,
            Swipe.action.in_([SwipeAction.superlike, SwipeAction.like]),
        )
        .correlate(Profile)
        .scalar_subquery()
    )

    priority_incoming = case(
        (incoming_action == SwipeAction.superlike, 2),
        (incoming_action == SwipeAction.like, 1),
        else_=0,
    )

    result = await db.execute(
        select(Profile)
        .options(selectinload(Profile.user).selectinload(User.university))
        .join(User, Profile.user_id == User.id)
        .where(
            and_(
                Profile.is_visible == True,
                is_complete_cond,
                User.is_active == True,
                ~Profile.user_id.in_(swiped_ids),
                *gender_filters,
                *search_filters,
            )
        )
        .order_by(
            priority_incoming.desc(),
            (User.premium_until > now).desc(),
            (User.boost_until > now).desc(),
            User.email_verified.desc(),
            Profile.rating_score.desc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_career_profile(
    db: AsyncSession, user_id: int, **kwargs
) -> Optional[Profile]:
    """Обновить профессиональную анкету (Карьера)."""
    profile = await get_profile(db, user_id)
    if not profile:
        profile = await create_profile(db, user_id)
    for key, value in kwargs.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return profile


# ─────────────────────────────────────────────────────────────
# Swipes & Matches
# ─────────────────────────────────────────────────────────────
async def create_swipe(
    db: AsyncSession, from_id: int, to_id: int, action: SwipeAction, comment: Optional[str] = None
) -> bool:
    """
    Сохранить свайп. Возвращает True если это взаимный лайк (мэтч).
    Защищён от дубликатов, состояний гонки и конфликтов авто-мэтчей.
    """
    try:
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
            # Если партнер — тестовый профиль со включенным авто-мэтчем
            target_user = await get_user(db, to_id)
            if target_user and getattr(target_user, "is_fake", False) and getattr(target_user, "auto_match_mode", "instant") == "instant":
                # Добавляем обратный свайп только если его ещё нет
                rev_fake = await db.execute(
                    select(Swipe).where(and_(Swipe.from_user_id == to_id, Swipe.to_user_id == from_id))
                )
                if not rev_fake.scalar_one_or_none():
                    db.add(Swipe(from_user_id=to_id, to_user_id=from_id, action=SwipeAction.like))
                
                # Добавляем Match только если его ещё нет
                exist_match = await db.execute(
                    select(Match).where(
                        or_(
                            and_(Match.user1_id == from_id, Match.user2_id == to_id),
                            and_(Match.user1_id == to_id, Match.user2_id == from_id),
                        )
                    )
                )
                if not exist_match.scalar_one_or_none():
                    from_user = await get_user(db, from_id)
                    user_mode = from_user.mode if from_user and from_user.mode else ModeEnum.dating
                    db.add(Match(user1_id=from_id, user2_id=to_id, mode=user_mode))
                
                await db.commit()
                return True

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
                # Добавляем Match только если его ещё нет
                exist_match = await db.execute(
                    select(Match).where(
                        or_(
                            and_(Match.user1_id == from_id, Match.user2_id == to_id),
                            and_(Match.user1_id == to_id, Match.user2_id == from_id),
                        )
                    )
                )
                if not exist_match.scalar_one_or_none():
                    from_user = await get_user(db, from_id)
                    user_mode = from_user.mode if from_user and from_user.mode else ModeEnum.dating
                    db.add(Match(user1_id=from_id, user2_id=to_id, mode=user_mode))
                    await db.commit()
                    return True
                else:
                    return False
        return False
    except Exception as e:
        await db.rollback()
        logger.warning(f"⚠️ Ошибка при обработке свайпа {from_id}->{to_id}: {e}")
        return False


async def get_user_matches(db: AsyncSession, user_id: int) -> List[Tuple[Match, User]]:
    """Получить список всех мэтчей пользователя с деталями о партнере."""
    query = (
        select(Match)
        .where(or_(Match.user1_id == user_id, Match.user2_id == user_id))
        .order_by(Match.created_at.desc())
    )
    result = await db.execute(query)
    matches = list(result.scalars().all())

    partner_matches = []
    for m in matches:
        partner_id = m.user2_id if m.user1_id == user_id else m.user1_id
        partner = await get_user(db, partner_id)
        if partner:
            partner_matches.append((m, partner))
    return partner_matches


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

    # Начисляем товар динамически на основе каталога
    try:
        from bot.utils.dynamic_settings import get_payment_products_catalog
        catalog = await get_payment_products_catalog()
        catalog_map = {p["id"]: p for p in catalog}
        prod_val = payment.product.value if hasattr(payment.product, 'value') else str(payment.product)
        prod_meta = catalog_map.get(prod_val)
        if prod_meta:
            btype = prod_meta.get("bonus_type")
            bval = int(prod_meta.get("bonus_value", 1))
            if btype == "superlikes":
                await add_superlikes(db, payment.user_id, bval)
            elif btype == "boost":
                boost_until = datetime.now(timezone.utc) + timedelta(hours=bval)
                await db.execute(update(User).where(User.id == payment.user_id).values(boost_until=boost_until))
            elif btype == "premium":
                await set_user_premium(db, payment.user_id, days=bval)
                await add_superlikes(db, payment.user_id, max(10, bval // 3))
        else:
            if payment.product == PaymentProduct.superlike_1:
                await add_superlikes(db, payment.user_id, 1)
            elif payment.product == PaymentProduct.superlike_3:
                await add_superlikes(db, payment.user_id, 3)
            elif payment.product == PaymentProduct.superlike_5:
                await add_superlikes(db, payment.user_id, 5)
            elif payment.product == PaymentProduct.superlike_10:
                await add_superlikes(db, payment.user_id, 10)
            elif payment.product == PaymentProduct.boost_24h:
                boost_until = datetime.now(timezone.utc) + timedelta(hours=24)
                await db.execute(update(User).where(User.id == payment.user_id).values(boost_until=boost_until))
            elif payment.product == PaymentProduct.premium_1m:
                await set_user_premium(db, payment.user_id, days=30)
                await add_superlikes(db, payment.user_id, 10)
    except Exception:
        pass

    await db.commit()
    return payment


# ─────────────────────────────────────────────────────────────
# Премиум и Входящие лайки
# ─────────────────────────────────────────────────────────────
async def set_user_premium(
    db: AsyncSession,
    user_id: int,
    days: Optional[int] = 30,
    until: Optional[datetime] = None,
) -> datetime:
    """Устанавливает или продлевает Premium-статус пользователя."""
    user = await get_user(db, user_id)
    now = datetime.now(timezone.utc)
    if until:
        new_premium_until = until
    else:
        current_until = user.premium_until if user else None
        if current_until and current_until.tzinfo is None:
            current_until = current_until.replace(tzinfo=timezone.utc)

        base_time = current_until if (current_until and current_until > now) else now
        new_premium_until = base_time + timedelta(days=days or 30)

    current_boost = user.boost_until if user else None
    if current_boost and current_boost.tzinfo is None:
        current_boost = current_boost.replace(tzinfo=timezone.utc)
    new_boost = max(current_boost or now, new_premium_until)

    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(premium_until=new_premium_until, boost_until=new_boost)
    )
    await db.commit()
    return new_premium_until


async def revoke_user_premium(db: AsyncSession, user_id: int) -> bool:
    """Снимает Premium-статус пользователя."""
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(premium_until=None)
    )
    await db.commit()
    return True


async def get_incoming_likes(
    db: AsyncSession, user_id: int, limit: int = 30
) -> List[Swipe]:
    """
    Возвращает список входящих лайков/суперлайков для user_id от пользователей,
    которым user_id ещё не поставил ответный свайп.
    """
    swiped_subq = select(Swipe.to_user_id).where(Swipe.from_user_id == user_id)

    result = await db.execute(
        select(Swipe)
        .options(
            selectinload(Swipe.from_user).selectinload(User.profile),
            selectinload(Swipe.from_user).selectinload(User.university),
        )
        .join(User, Swipe.from_user_id == User.id)
        .join(Profile, Profile.user_id == User.id)
        .where(
            Swipe.to_user_id == user_id,
            Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
            User.is_active == True,
            Profile.is_visible == True,
            ~Swipe.from_user_id.in_(swiped_subq),
        )
        .order_by(
            case((Swipe.action == SwipeAction.superlike, 1), else_=0).desc(),
            Swipe.created_at.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_incoming_likes_count(db: AsyncSession, user_id: int) -> int:
    """Количество непросмотренных входящих лайков."""
    swiped_subq = select(Swipe.to_user_id).where(Swipe.from_user_id == user_id)
    result = await db.scalar(
        select(func.count(Swipe.id))
        .join(User, Swipe.from_user_id == User.id)
        .where(
            Swipe.to_user_id == user_id,
            Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
            User.is_active == True,
            ~Swipe.from_user_id.in_(swiped_subq),
        )
    )
    return result or 0


# ─────────────────────────────────────────────────────────────
# Employer Access
# ─────────────────────────────────────────────────────────────
async def get_employer_profiles(
    db: AsyncSession, employer_id: int, status: Optional[str] = None
) -> List[EmployerProfileAccess]:
    query = (
        select(EmployerProfileAccess)
        .options(
            selectinload(EmployerProfileAccess.profile)
            .selectinload(Profile.user)
            .selectinload(User.university)
        )
        .where(EmployerProfileAccess.employer_id == employer_id)
    )

    if status and status != "all":
        if status == "suitable":
            query = query.where(EmployerProfileAccess.status == "suitable")
        elif status == "archived":
            query = query.where(EmployerProfileAccess.status.in_(["archived", "rejected"]))
        elif status == "active":
            query = query.where(EmployerProfileAccess.status.in_(["active", "new", "screening", "interview", "offer", "hired", None]))
        else:
            query = query.where(EmployerProfileAccess.status == status)

    query = query.order_by(EmployerProfileAccess.granted_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_employer_profile_counts(db: AsyncSession, employer_id: int) -> dict:
    """Возвращает количество кандидатов по категориям и этапам воронки."""
    all_res = await db.execute(
        select(EmployerProfileAccess.status, func.count(EmployerProfileAccess.id))
        .where(EmployerProfileAccess.employer_id == employer_id)
        .group_by(EmployerProfileAccess.status)
    )
    counts = {
        "all": 0,
        "new": 0,
        "screening": 0,
        "interview": 0,
        "offer": 0,
        "hired": 0,
        "archived": 0,
        "rejected": 0,
        "suitable": 0,
        "active": 0,
    }
    for st, cnt in all_res.all():
        st_clean = st or "new"
        if st_clean in counts:
            counts[st_clean] += cnt
        else:
            counts["new"] += cnt
        counts["all"] += cnt
        if st_clean in ("new", "screening", "interview", "offer", "hired", "active", None):
            counts["active"] += cnt
    return counts


async def mark_profile_viewed(db: AsyncSession, access_id) -> None:
    await db.execute(
        update(EmployerProfileAccess)
        .where(EmployerProfileAccess.id == access_id)
        .values(viewed_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def update_employer_candidate_status(
    db: AsyncSession,
    access_id,
    employer_id: int,
    new_status: Optional[str] = None,
    hr_comment: Optional[str] = None,
    hr_rating: Optional[int] = None,
    hr_recommendation: Optional[str] = None,
    hr_tags: Optional[str] = None,
) -> Optional[EmployerProfileAccess]:
    result = await db.execute(
        select(EmployerProfileAccess).where(
            EmployerProfileAccess.id == access_id,
            EmployerProfileAccess.employer_id == employer_id,
        )
    )
    access = result.scalar_one_or_none()
    if access:
        if new_status:
            access.status = new_status
        if hr_comment is not None:
            access.hr_comment = hr_comment
        if hr_rating is not None:
            access.hr_rating = hr_rating
        if hr_recommendation is not None:
            access.hr_recommendation = hr_recommendation
        if hr_tags is not None:
            access.hr_tags = hr_tags
        await db.commit()
        await db.refresh(access)
    return access
