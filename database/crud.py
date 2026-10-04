"""
CRUD-операции для основных сущностей.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Collection, Set, Any, Union
import uuid
import random
import string
import logging
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, func, case, exists, Float
from sqlalchemy.sql import expression
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from database.models import (
    User, Profile, University, EmailToken, Achievement,
    Swipe, Match, ChatMessage, Admin, Employer, EmployerProfileAccess, Payment, Report,
    VerifiedStatus, SwipeAction, ModeEnum, PaymentStatus, PaymentProduct, UserPrivacy,
    Project, ShopItem, EconomyTransaction, UserDailyQuest, UserPermanentQuest, UserInventoryItem,
    UserReceivedGift,
)


class random_normalized(expression.FunctionElement):
    """Возвращает случайное число [0.0, 1.0) для PostgreSQL и SQLite."""
    type = Float()
    inherit_cache = True


@compiles(random_normalized, "postgresql")
def compile_random_pg(element, compiler, **kw):
    return "random()"


@compiles(random_normalized, "sqlite")
def compile_random_sqlite(element, compiler, **kw):
    return "(abs(random()) % 1000) / 1000.0"


@compiles(random_normalized)
def compile_random_default(element, compiler, **kw):
    return "random()"



# ─────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────
async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.profile), selectinload(User.university), selectinload(User.privacy))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_user(db: AsyncSession, user_id: int, tg_username: Optional[str] = None) -> User:
    user = await get_user(db, user_id)
    if not user:
        user = User(id=user_id, tg_username=tg_username, university_id=1)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        updated = False
        if tg_username and user.tg_username != tg_username:
            user.tg_username = tg_username
            updated = True
        if user.university_id is None:
            user.university_id = 1
            updated = True
        if updated:
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


_user_active_cache: dict = {}


async def update_user_last_active(db: AsyncSession, user_id: int, force: bool = False) -> None:
    """
    Обновляет время последней активности пользователя (last_active_at) с троттлингом (не чаще 1 раза в 60 сек).
    """
    import time
    now_ts = time.time()
    last_ts = _user_active_cache.get(user_id, 0)
    if not force and (now_ts - last_ts < 60):
        return
    _user_active_cache[user_id] = now_ts
    try:
        now_utc = datetime.now(timezone.utc)
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_active_at=now_utc)
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to update last_active_at for user {user_id}: {e}")


async def transfer_superlike_rating(db: AsyncSession, from_user_id: int, to_user_id: int) -> dict:
    """
    Передать 1 суперлайк от from_user_id пользователю to_user_id в виде +1 к его Profile.rating_score.
    Атомарная операция: списывает 1 суперлайк с баланса и начисляет +1.0 к рейтингу.
    """
    if from_user_id == to_user_id:
        return {"success": False, "error": "self_transfer_forbidden"}

    target_user = await get_user(db, to_user_id)
    if not target_user or not target_user.profile:
        return {"success": False, "error": "target_not_found"}

    deducted = await deduct_superlike(db, from_user_id)
    if not deducted:
        sender = await get_user(db, from_user_id)
        remaining = sender.superlike_balance if sender else 0
        return {
            "success": False,
            "error": "insufficient_balance",
            "remaining_superlikes": remaining,
        }

    await db.execute(
        update(Profile)
        .where(Profile.id == target_user.profile.id)
        .values(rating_score=func.coalesce(Profile.rating_score, 0.0) + 1.0)
    )
    await db.commit()

    sender = await get_user(db, from_user_id)
    refreshed_target = await get_user(db, to_user_id)

    new_target_rating = round(refreshed_target.profile.rating_score or 0.0, 1) if (refreshed_target and refreshed_target.profile) else 0.0
    remaining_superlikes = sender.superlike_balance if sender else 0

    return {
        "success": True,
        "new_target_rating": new_target_rating,
        "remaining_superlikes": remaining_superlikes,
        "target_name": (refreshed_target.profile.name if refreshed_target and refreshed_target.profile else "Студент"),
        "sender_name": (sender.profile.name if sender and sender.profile else "Студент"),
    }


# ─────────────────────────────────────────────────────────────
# Privacy Settings (UserPrivacy)
# ─────────────────────────────────────────────────────────────
def _normalize_private_photos(val) -> List[str]:
    if val is None:
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            return [val] if val else []
    return [str(x) for x in list(val)]


async def get_or_create_user_privacy(db: AsyncSession, user_id: int) -> UserPrivacy:
    """Получить или создать дефолтные настройки приватности для пользователя."""
    res = await db.execute(select(UserPrivacy).where(UserPrivacy.user_id == user_id))
    privacy = res.scalar_one_or_none()
    if not privacy:
        privacy = UserPrivacy(
            user_id=user_id,
            online_visibility="all",
            message_permission="matches",
            allow_employer_access=True,
            hide_age=False,
            hide_course=False,
            hide_email=False,
            private_photos=[],
        )
        db.add(privacy)
        try:
            await db.commit()
            await db.refresh(privacy)
        except IntegrityError:
            await db.rollback()
            res = await db.execute(select(UserPrivacy).where(UserPrivacy.user_id == user_id))
            privacy = res.scalar_one_or_none()
    if privacy:
        privacy.private_photos = _normalize_private_photos(privacy.private_photos)
    return privacy


async def update_user_privacy(db: AsyncSession, user_id: int, **fields) -> UserPrivacy:
    """Обновить настройки приватности пользователя."""
    privacy = await get_or_create_user_privacy(db, user_id)
    allowed = {
        "online_visibility", "message_permission", "allow_employer_access",
        "hide_age", "hide_course", "hide_email", "private_photos"
    }
    for key, value in fields.items():
        if key in allowed and value is not None:
            if key == "private_photos":
                value = _normalize_private_photos(value)
            setattr(privacy, key, value)
    privacy.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(privacy)
    privacy.private_photos = _normalize_private_photos(privacy.private_photos)
    return privacy


async def toggle_photo_privacy(db: AsyncSession, user_id: int, photo_id: str) -> Tuple[UserPrivacy, bool]:
    """
    Переключить видимость дополнительного фото:
    Если было в private_photos — удаляет (становится открытым всем).
    Если не было — добавляет (становится доступно только взаимным мэтчам).
    Возвращает (privacy, is_now_private).
    """
    privacy = await get_or_create_user_privacy(db, user_id)
    current = _normalize_private_photos(privacy.private_photos)
    clean_id = str(photo_id).strip()
    if clean_id in current:
        current.remove(clean_id)
        is_now_private = False
    else:
        current.append(clean_id)
        is_now_private = True

    privacy.private_photos = current
    privacy.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(privacy)
    privacy.private_photos = current
    return privacy, is_now_private


def is_user_online_visible_to(viewer_id: int, target_user: User, is_mutual_match: bool = False) -> bool:
    """
    Проверяет, виден ли статус онлайн target_user для viewer_id с учётом настроек приватности.
    Односторонняя приватность:
    - Если 'nobody': никто не видит (кроме самого себя).
    - Если 'matches': видят только взаимные мэтчи (и сам пользователь).
    - Если 'all': видят все.
    """
    if viewer_id == target_user.id:
        return target_user.is_online

    privacy = getattr(target_user, "privacy", None)
    vis = privacy.online_visibility if privacy else "all"
    if vis == "nobody":
        return False
    if vis == "matches" and not is_mutual_match:
        return False
    return target_user.is_online


def get_user_online_status_text_for(viewer_id: int, target_user: User, is_mutual_match: bool = False) -> str:
    """Возвращает статус активности target_user для viewer_id с учётом настроек приватности."""
    if is_user_online_visible_to(viewer_id, target_user, is_mutual_match):
        return target_user.online_status_text
    return "был(а) недавно"


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
    if mode == ModeEnum.career:
        is_complete_cond = (Profile.career_is_complete == True)
    elif mode == ModeEnum.projects:
        is_complete_cond = or_(Profile.project_is_complete == True, Profile.is_complete == True)
    else:
        is_complete_cond = (Profile.is_complete == True)

    result = await db.execute(
        select(Profile)
        .options(
            selectinload(Profile.user).selectinload(User.university),
            selectinload(Profile.user).selectinload(User.privacy),
        )
        .join(User, Profile.user_id == User.id)
        .where(
            and_(
                Profile.is_visible == True,
                is_complete_cond,
                User.is_active == True,
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
    exclude_ids: Optional[Collection[int]] = None,
) -> Optional[Profile]:
    """
    Умный бесконечный алгоритм выдачи анкет:
    1. Исключаем: самого пользователя, жалобы (Report), положительные свайпы (like/superlike),
       активные мэтчи в этом режиме, а также скользящий буфер недавно свайпнутых анкет.
    2. Приоритеты (4-уровневый водопад):
       - Tier 1: Входящий суперлайк (приоритет 4) и входящий лайк (приоритет 3).
         Если пропущенный кандидат лайкнул пользователя — сразу всплывает на 1-е место!
       - Tier 2: Свежие непросмотренные анкеты (приоритет 2).
       - Tier 3: Ресайкл пропусков старше 48 часов (приоритет 1).
       - Tier 4: Fallback ресайкл самых давних пропусков (FIFO) для бесконечной ленты (приоритет 0).
    3. Сортировка: Приоритет → Буст → Премиум → Верификация → (FIFO для ресайкла / Рейтинг для свежих).
    """
    now = datetime.now(timezone.utc)
    current_mode = mode or ModeEnum.dating
    cooldown_threshold = now - timedelta(hours=48)

    # 1. Загружаем профиль смотрящего для фильтрации
    viewer_profile = await get_profile(db, viewer_id)

    # Фильтры для режима Знакомств (гендер)
    gender_filters = []
    if current_mode == ModeEnum.dating and viewer_profile:
        if viewer_profile.target_gender == "female":
            gender_filters.append(or_(Profile.gender == "female", Profile.gender.is_(None), Profile.gender == ""))
        elif viewer_profile.target_gender == "male":
            gender_filters.append(or_(Profile.gender == "male", Profile.gender.is_(None), Profile.gender == ""))

        if viewer_profile.gender == "male":
            gender_filters.append(
                or_(
                    Profile.target_gender == "male",
                    Profile.target_gender == "all",
                    Profile.target_gender.is_(None),
                    Profile.target_gender == "",
                )
            )
        elif viewer_profile.gender == "female":
            gender_filters.append(
                or_(
                    Profile.target_gender == "female",
                    Profile.target_gender == "all",
                    Profile.target_gender.is_(None),
                    Profile.target_gender == "",
                )
            )

    # Фильтры поиска (возраст, курс, факультет)
    search_filters = []
    if viewer_profile:
        min_a = viewer_profile.filter_min_age
        max_a = viewer_profile.filter_max_age
        if min_a and max_a:
            search_filters.append(
                or_(
                    Profile.age.is_(None),
                    and_(Profile.age >= min_a, Profile.age <= max_a),
                )
            )

        min_y = viewer_profile.filter_min_year
        max_y = viewer_profile.filter_max_year
        if min_y and max_y:
            search_filters.append(
                or_(
                    Profile.year.is_(None),
                    and_(Profile.year >= min_y, Profile.year <= max_y),
                )
            )

        f_major = viewer_profile.filter_major
        if f_major and f_major != "all":
            search_filters.append(
                or_(
                    Profile.major.is_(None),
                    Profile.major.ilike(f"%{f_major}%"),
                )
            )

    if current_mode == ModeEnum.career:
        is_complete_cond = (Profile.career_is_complete == True)
    elif current_mode == ModeEnum.projects:
        is_complete_cond = or_(Profile.project_is_complete == True, Profile.is_complete == True)
    else:
        is_complete_cond = (Profile.is_complete == True)

    # Исключение жалоб
    reported_subq = exists(
        select(1).where(
            and_(
                Report.reporter_id == viewer_id,
                Report.reported_id == Profile.user_id,
            )
        )
    )

    # Исключение положительных свайпов (like / superlike) от смотрящего в этом режиме
    liked_subq = exists(
        select(1).where(
            and_(
                Swipe.from_user_id == viewer_id,
                Swipe.to_user_id == Profile.user_id,
                or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
                Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
            )
        )
    )

    # Исключение уже существующих взаимных мэтчей в этом режиме
    matched_subq = exists(
        select(1).where(
            and_(
                Match.mode == current_mode,
                or_(
                    and_(Match.user1_id == viewer_id, Match.user2_id == Profile.user_id),
                    and_(Match.user1_id == Profile.user_id, Match.user2_id == viewer_id),
                ),
            )
        )
    )

    # Подзапрос входящих симпатий кандидата к смотрящему
    incoming_action = (
        select(Swipe.action)
        .where(
            Swipe.from_user_id == Profile.user_id,
            Swipe.to_user_id == viewer_id,
            or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
            Swipe.action.in_([SwipeAction.superlike, SwipeAction.like]),
        )
        .order_by(Swipe.created_at.desc())
        .limit(1)
        .correlate(Profile)
        .scalar_subquery()
    )
    incoming_time = (
        select(Swipe.created_at)
        .where(
            Swipe.from_user_id == Profile.user_id,
            Swipe.to_user_id == viewer_id,
            or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
            Swipe.action.in_([SwipeAction.superlike, SwipeAction.like]),
        )
        .order_by(Swipe.created_at.desc())
        .limit(1)
        .correlate(Profile)
        .scalar_subquery()
    )

    # Подзапрос действия и времени свайпа смотрящего к кандидату
    viewer_swipe_action = (
        select(Swipe.action)
        .where(
            Swipe.from_user_id == viewer_id,
            Swipe.to_user_id == Profile.user_id,
            or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
        )
        .order_by(Swipe.created_at.desc())
        .limit(1)
        .correlate(Profile)
        .scalar_subquery()
    )
    viewer_swipe_time = (
        select(Swipe.created_at)
        .where(
            Swipe.from_user_id == viewer_id,
            Swipe.to_user_id == Profile.user_id,
            or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
        )
        .order_by(Swipe.created_at.desc())
        .limit(1)
        .correlate(Profile)
        .scalar_subquery()
    )

    # Входящий лайк считается АКТИВНЫМ, если смотрящий его еще не видел/не скипал
    # (viewer_swipe_time is NULL) либо если кандидат поставил новый лайк ПОСЛЕ того, как смотрящий скипнул (incoming_time > viewer_swipe_time)
    is_active_incoming = and_(
        incoming_action.isnot(None),
        or_(viewer_swipe_time.is_(None), incoming_time > viewer_swipe_time),
    )

    # Вычисление уровней приоритета (Priority Tiers):
    # Tier 1: Активный входящий superlike (4) / like (3)
    # Tier 2: Свежие непросмотренные анкеты (2)
    # Tier 3: Ресайкл пропусков старше 48ч (1)
    # Tier 4: Fallback ресайкл недавних пропусков (0)
    priority = case(
        (and_(is_active_incoming, incoming_action == SwipeAction.superlike), 4),
        (and_(is_active_incoming, incoming_action == SwipeAction.like), 3),
        (viewer_swipe_action.is_(None), 2),
        (
            and_(
                viewer_swipe_action == SwipeAction.skip,
                viewer_swipe_time < cooldown_threshold,
            ),
            1,
        ),
        else_=0,
    )

    # Получаем последние 60 свайпов пользователя для скользящего буфера
    recent_swipes_res = await db.execute(
        select(Swipe.to_user_id)
        .where(
            Swipe.from_user_id == viewer_id,
            or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
        )
        .order_by(Swipe.created_at.desc())
        .limit(60)
    )
    recent_swiped_ids = list(recent_swipes_res.scalars().all())

    # Базовые условия выборки (исключаем анкеты-пустышки без фото, без имени или с дефолтным "Студент")
    base_conditions = [
        Profile.is_visible == True,
        is_complete_cond,
        User.is_active == True,
        Profile.user_id != viewer_id,
        Profile.name.isnot(None),
        Profile.name != "",
        Profile.name != "Студент",
        or_(
            Profile.avatar_file_id.isnot(None),
            Profile.career_avatar_file_id.isnot(None),
        ),
        ~reported_subq,
        ~liked_subq,
        ~matched_subq,
        *gender_filters,
        *search_filters,
    ]

    base_query = (
        select(Profile)
        .options(
            selectinload(Profile.user).selectinload(User.university),
            selectinload(Profile.user).selectinload(User.privacy),
        )
        .join(User, Profile.user_id == User.id)
        .order_by(
            priority.desc(),
            (User.boost_until > now).desc(),
            (User.premium_until > now).desc(),
            User.email_verified.desc(),
            # Взвешенный джиттер для свежих анкет (priority == 2): рейтинг дает преимущество, но с рандомизацией
            case(
                (priority == 2, Profile.rating_score * 0.7 + (random_normalized() * 35.0)),
                else_=None,
            ).desc().nulls_last(),
            # Случайный порядок для ресайкла скипов (priority <= 1), ломающий зацикленный круг FIFO
            case(
                (priority <= 1, random_normalized()),
                else_=None,
            ).desc().nulls_last(),
            Profile.rating_score.desc(),
        )
        .limit(1)
    )

    # Проход 1: Со скользящим буфером (исключаем последние 50 свайпов, кроме активных входящих лайков)
    client_exclude: Set[int] = set(exclude_ids or ())
    recent_buffer: Set[int] = set(recent_swiped_ids[:50])

    q1_conds = list(base_conditions)
    if client_exclude:
        q1_conds.append(Profile.user_id.not_in(client_exclude))
    if recent_buffer:
        q1_conds.append(
            or_(
                is_active_incoming,
                Profile.user_id.not_in(recent_buffer),
            )
        )

    q1 = base_query.where(and_(*q1_conds))
    result = await db.execute(q1)
    candidate = result.scalar_one_or_none()
    if candidate:
        return candidate

    # Проход 2: Fallback при маленьком пуле анкет (без жесткого буфера, но исключая самую последнюю карточку)
    q2_conds = list(base_conditions)
    if client_exclude:
        q2_conds.append(Profile.user_id.not_in(client_exclude))
    if recent_swiped_ids:
        q2_conds.append(
            or_(
                is_active_incoming,
                Profile.user_id != recent_swiped_ids[0],
            )
        )

    q2 = base_query.where(and_(*q2_conds))
    result2 = await db.execute(q2)
    candidate2 = result2.scalar_one_or_none()
    if candidate2:
        return candidate2

    # Проход 3: Ultimate Fallback (если пул <= 1 или все доступные анкеты в recent_swiped_ids[0])
    # Убираем ограничение на recent_swiped_ids[0], сохраняя только client_exclude
    q3_conds = list(base_conditions)
    if client_exclude:
        q3_conds.append(Profile.user_id.not_in(client_exclude))

    q3 = base_query.where(and_(*q3_conds))
    result3 = await db.execute(q3)
    return result3.scalar_one_or_none()


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
    db: AsyncSession,
    from_id: int,
    to_id: int,
    action: SwipeAction,
    mode: ModeEnum = ModeEnum.dating,
    comment: Optional[str] = None,
    to_project_id: Optional[uuid.UUID] = None,
) -> bool:
    """
    Сохранить свайп с учётом режима (Dating / Career / Projects).
    Возвращает True если это взаимный лайк (мэтч).
    При повторном свайпе (даже skip) обновляет created_at для корректной работы кулдауна.
    """
    try:
        now = datetime.now(timezone.utc)
        current_mode = mode or ModeEnum.dating
        # Проверяем, не было ли уже свайпа в этом режиме
        if to_project_id:
            match_cond = and_(
                Swipe.from_user_id == from_id,
                Swipe.to_project_id == to_project_id,
            )
        else:
            match_cond = and_(
                Swipe.from_user_id == from_id,
                Swipe.to_user_id == to_id,
                Swipe.to_project_id.is_(None),
                or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
            )

        existing = await db.execute(
            select(Swipe).where(match_cond).order_by(Swipe.created_at.desc()).limit(1)
        )
        existing_swipe = existing.scalar_one_or_none()
        if existing_swipe:
            existing_swipe.mode = current_mode
            if to_project_id:
                existing_swipe.to_project_id = to_project_id
            if existing_swipe.action == action and action in (SwipeAction.like, SwipeAction.superlike):
                return False
            existing_swipe.action = action
            existing_swipe.created_at = now
            if comment is not None:
                existing_swipe.comment = comment
        else:
            try:
                async with db.begin_nested():
                    db.add(
                        Swipe(
                            from_user_id=from_id,
                            to_user_id=to_id,
                            to_project_id=to_project_id,
                            mode=current_mode,
                            action=action,
                            comment=comment,
                            created_at=now,
                        )
                    )
                    await db.flush()
            except IntegrityError:
                existing = await db.execute(
                    select(Swipe).where(match_cond).order_by(Swipe.created_at.desc()).limit(1)
                )
                existing_swipe = existing.scalar_one_or_none()
                if existing_swipe:
                    if existing_swipe.action == action and action in (SwipeAction.like, SwipeAction.superlike):
                        return False
                    existing_swipe.action = action
                    existing_swipe.created_at = now
                    if comment is not None:
                        existing_swipe.comment = comment

        # Если отправлен суперлайк — начисляем получателю +1 балл к рейтингу
        if action == SwipeAction.superlike:
            await db.execute(
                update(Profile)
                .where(Profile.user_id == to_id)
                .values(rating_score=func.coalesce(Profile.rating_score, 0.0) + 1.0)
            )

        await db.commit()

        # Проверяем взаимный лайк в этом же режиме
        if action in (SwipeAction.like, SwipeAction.superlike):
            # Если партнер — тестовый профиль со включенным авто-мэтчем
            target_user = await get_user(db, to_id)
            if target_user and getattr(target_user, "is_fake", False) and getattr(target_user, "auto_match_mode", "instant") == "instant":
                rev_fake = await db.execute(
                    select(Swipe).where(
                        and_(
                            Swipe.from_user_id == to_id,
                            Swipe.to_user_id == from_id,
                            Swipe.mode == current_mode,
                        )
                    )
                )
                if not rev_fake.scalar_one_or_none():
                    try:
                        async with db.begin_nested():
                            db.add(Swipe(from_user_id=to_id, to_user_id=from_id, mode=current_mode, action=SwipeAction.like, created_at=now))
                            await db.flush()
                    except IntegrityError:
                        pass

                exist_match = await db.execute(
                    select(Match).where(
                        and_(
                            Match.mode == current_mode,
                            or_(
                                and_(Match.user1_id == from_id, Match.user2_id == to_id),
                                and_(Match.user1_id == to_id, Match.user2_id == from_id),
                            ),
                        )
                    )
                )
                if not exist_match.scalar_one_or_none():
                    try:
                        async with db.begin_nested():
                            db.add(Match(user1_id=from_id, user2_id=to_id, mode=current_mode))
                            await db.flush()
                        await db.commit()
                        return True
                    except IntegrityError:
                        await db.commit()
                        return True
                return False

            reverse = await db.execute(
                select(Swipe).where(
                    and_(
                        Swipe.from_user_id == to_id,
                        Swipe.to_user_id == from_id,
                        Swipe.mode == current_mode,
                        Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
                    )
                )
            )
            if reverse.scalar_one_or_none():
                exist_match = await db.execute(
                    select(Match).where(
                        and_(
                            Match.mode == current_mode,
                            or_(
                                and_(Match.user1_id == from_id, Match.user2_id == to_id),
                                and_(Match.user1_id == to_id, Match.user2_id == from_id),
                            ),
                        )
                    )
                )
                if not exist_match.scalar_one_or_none():
                    try:
                        async with db.begin_nested():
                            db.add(Match(user1_id=from_id, user2_id=to_id, mode=current_mode))
                            await db.flush()
                        await db.commit()
                        return True
                    except IntegrityError:
                        await db.commit()
                        return True
                return False
        return False
    except Exception as e:
        await db.rollback()
        logger.warning(f"⚠️ Ошибка при обработке свайпа {from_id}->{to_id}: {e}")
        return False


async def get_user_matches(
    db: AsyncSession, user_id: int, mode: Optional[ModeEnum] = None
) -> List[Tuple[Match, User]]:
    """Получить список всех мэтчей пользователя с деталями о партнере (с фильтрацией по режиму)."""
    # 1. Автоматический бекфилл/исправление: находим все взаимные лайки, у которых нет записи в matches
    try:
        current_mode = mode or ModeEnum.dating
        likes_cond = [
            Swipe.from_user_id == user_id,
            Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
        ]
        if mode:
            likes_cond.append(Swipe.mode == current_mode)

        my_likes_res = await db.execute(select(Swipe.to_user_id).where(and_(*likes_cond)))
        my_liked_ids = [uid for uid in my_likes_res.scalars().all() if uid and uid != user_id]

        if my_liked_ids:
            mutual_cond = [
                Swipe.from_user_id.in_(my_liked_ids),
                Swipe.to_user_id == user_id,
                Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
            ]
            if mode:
                mutual_cond.append(Swipe.mode == current_mode)

            mutual_res = await db.execute(select(Swipe.from_user_id).where(and_(*mutual_cond)))
            mutual_ids = [uid for uid in mutual_res.scalars().all() if uid and uid != user_id]

            if mutual_ids:
                # Проверяем существование партнеров в БД одним запросом
                valid_partners_res = await db.execute(
                    select(User.id).where(User.id.in_(mutual_ids))
                )
                valid_partner_ids = set(valid_partners_res.scalars().all())

                for partner_id in mutual_ids:
                    if partner_id not in valid_partner_ids:
                        continue

                    match_check_cond = [
                        or_(
                            and_(Match.user1_id == user_id, Match.user2_id == partner_id),
                            and_(Match.user1_id == partner_id, Match.user2_id == user_id),
                        )
                    ]
                    if mode:
                        match_check_cond.append(Match.mode == current_mode)

                    exist_match = await db.scalar(select(Match).where(and_(*match_check_cond)))
                    if not exist_match:
                        db.add(Match(id=uuid.uuid4(), user1_id=user_id, user2_id=partner_id, mode=current_mode))
                await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Failed to auto-heal matches for user {user_id}: {e}")

    # 2. Выбираем все актуальные мэтчи с пакетной загрузкой партнеров (устранение N+1)
    try:
        query = (
            select(Match)
            .options(selectinload(Match.project))
            .where(or_(Match.user1_id == user_id, Match.user2_id == user_id))
        )
        if mode:
            query = query.where(Match.mode == mode)
        query = query.order_by(Match.created_at.desc())

        result = await db.execute(query)
        matches = list(result.scalars().all())

        if not matches:
            return []

        # Собираем уникальные ID партнеров
        seen_pids = set()
        partner_ids = []
        for m in matches:
            pid = m.user2_id if m.user1_id == user_id else m.user1_id
            if pid not in seen_pids and pid != user_id:
                seen_pids.add(pid)
                partner_ids.append(pid)

        # Пакетная загрузка всех партнеров одним SQL-запросом с жадной загрузкой профиля и ВУЗа
        partners_map = {}
        if partner_ids:
            partners_res = await db.execute(
                select(User)
                .options(
                    selectinload(User.profile),
                    selectinload(User.university),
                    selectinload(User.privacy),
                )
                .where(User.id.in_(partner_ids))
            )
            for u in partners_res.scalars().all():
                partners_map[u.id] = u

        partner_matches = []
        added_keys = set()
        for m in matches:
            partner_id = m.user2_id if m.user1_id == user_id else m.user1_id
            if partner_id == user_id:
                continue
            # Составной ключ: разделяет диалоги одного партнёра по режимам и проектам
            match_key = (partner_id, m.mode, m.project_id)
            if match_key in added_keys:
                continue
            partner = partners_map.get(partner_id)
            if partner and getattr(partner, "is_active", True):
                added_keys.add(match_key)
                partner_matches.append((m, partner))
        return partner_matches
    except Exception as e:
        await db.rollback()
        logger.error(f"Error querying matches for user {user_id}: {e}", exc_info=True)
        return []


# ─────────────────────────────────────────────────────────────
# Chat & Telegram Reveal
# ─────────────────────────────────────────────────────────────
async def get_match_by_id(db: AsyncSession, match_id: uuid.UUID) -> Optional[Match]:
    """Получить матч по его UUID."""
    res = await db.execute(select(Match).where(Match.id == match_id))
    return res.scalar_one_or_none()


async def get_match_between_users(
    db: AsyncSession, user1_id: int, user2_id: int, mode: Optional[ModeEnum] = None
) -> Optional[Match]:
    """Найти существующий матч между двумя пользователями."""
    query = (
        select(Match)
        .options(selectinload(Match.project))
        .where(
            or_(
                and_(Match.user1_id == user1_id, Match.user2_id == user2_id),
                and_(Match.user1_id == user2_id, Match.user2_id == user1_id),
            )
        )
    )
    if mode:
        query = query.where(Match.mode == mode)
    res = await db.execute(query.order_by(Match.created_at.desc()).limit(1))
    return res.scalar_one_or_none()


async def get_chat_messages(
    db: AsyncSession, match_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> List[ChatMessage]:
    """Получить историю сообщений для матча, отсортированную по возрастанию времени."""
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.match_id == match_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(res.scalars().all())


async def create_chat_message(
    db: AsyncSession,
    match_id: uuid.UUID,
    sender_id: int,
    text: str,
    msg_type: str = "text",
) -> ChatMessage:
    """Создать новое сообщение во внутреннем чате."""
    msg = ChatMessage(
        id=uuid.uuid4(),
        match_id=match_id,
        sender_id=sender_id,
        text=text.strip()[:2000],
        msg_type=msg_type,
        is_read=False,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def mark_chat_messages_as_read(
    db: AsyncSession, match_id: uuid.UUID, reader_id: int
) -> int:
    """Пометить входящие сообщения как прочитанные."""
    res = await db.execute(
        update(ChatMessage)
        .where(
            and_(
                ChatMessage.match_id == match_id,
                ChatMessage.sender_id != reader_id,
                ChatMessage.is_read == False,
            )
        )
        .values(is_read=True)
    )
    await db.commit()
    return res.rowcount or 0


async def get_unread_messages_count(
    db: AsyncSession, match_id: uuid.UUID, reader_id: int
) -> int:
    """Получить количество непрочитанных сообщений в данном чате."""
    res = await db.scalar(
        select(func.count(ChatMessage.id)).where(
            and_(
                ChatMessage.match_id == match_id,
                ChatMessage.sender_id != reader_id,
                ChatMessage.is_read == False,
            )
        )
    )
    return res or 0


async def get_last_chat_message(
    db: AsyncSession, match_id: uuid.UUID
) -> Optional[ChatMessage]:
    """Получить самое последнее сообщение в диалоге."""
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.match_id == match_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def approve_match_telegram(
    db: AsyncSession, match_id: uuid.UUID, user_id: int
) -> Tuple[Optional[Match], bool]:
    """
    Дать разрешение на открытие Telegram для указанного участника.
    Возвращает (match, is_now_unlocked): True если оба теперь одобрили контакт.
    """
    res = await db.execute(select(Match).where(Match.id == match_id))
    match = res.scalar_one_or_none()
    if not match:
        return None, False

    if match.user1_id == user_id:
        match.user1_tg_approved = True
    elif match.user2_id == user_id:
        match.user2_tg_approved = True
    else:
        return match, False

    was_unlocked = bool(match.tg_unlocked_at is not None)
    is_now_unlocked = bool(match.user1_tg_approved and match.user2_tg_approved)

    if is_now_unlocked and not was_unlocked:
        match.tg_unlocked_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(match)
    return match, (is_now_unlocked and not was_unlocked)


async def delete_match_by_id(
    db: AsyncSession, match_id: uuid.UUID, user_id: int
) -> bool:
    """Удалить мэтч и связанный чат (доступно только участнику матча)."""
    res = await db.execute(select(Match).where(Match.id == match_id))
    match = res.scalar_one_or_none()
    if not match:
        return False
    if match.user1_id != user_id and match.user2_id != user_id:
        return False
    await db.delete(match)
    await db.commit()
    return True



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

ACHIEVEMENT_LABELS = {
    "case_participant": "💼 Участие в хакатоне / кейс-чемпионате",
    "place_3": "🥉 Призовое 3-е место",
    "place_2": "🥈 Призовое 2-е место",
    "place_1": "🥇 Победа / 1-е место",
    "volunteer": "🤝 Участие в волонтёрском проекте",
    "internship": "👔 Прохождение стажировки",
    "forum_attender": "🏛 Посещение форума / конференции",
    "forum_speaker": "🎤 Выступление на форуме / конференции",
    # Дополнительные / устаревшие типы
    "gpa": "📊 GPA / Успеваемость",
    "competition": "🥇 Соревнования",
    "case": "💼 Кейс-чемпионат",
    "olympiad": "🏆 Победа в олимпиаде",
    "diploma": "🎓 Диплом с отличием",
    "publication": "📝 Публикация",
    "participation": "🎯 Участие",
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
            elif btype == "credits":
                await add_user_credits(db, payment.user_id, bval, tx_type="donate", description=f"Покупка зачётов ({payment.amount_rub} ₽)", reference_id=prod_val)
        else:
            if prod_val == "starter_pack_99" or payment.product == PaymentProduct.starter_pack_99:
                # Стартовый набор первокурсника (99 ₽):
                # 1. 300 Зачётов на баланс
                await add_user_credits(
                    db,
                    payment.user_id,
                    300,
                    tx_type="donate",
                    description="Стартовый набор первокурсника (99 ₽)",
                    reference_id="starter_pack_99",
                )
                user = await get_user(db, payment.user_id)
                if user:
                    # 2. Отмечаем флаг покупки (ограничен 1 на аккаунт)
                    user.has_bought_starter_pack = True
                    # 3. Буст анкеты 24ч
                    now = datetime.now(timezone.utc)
                    base_boost = user.boost_until if user.boost_until and user.boost_until > now else now
                    user.boost_until = base_boost + timedelta(hours=24)
                    # 4. 1 «Справка от врача» (защита стрика)
                    user.streak_freeze_count = (user.streak_freeze_count or 0) + 1
                    # 5. 3 «Шпоры» (откат свайпа) в инвентарь
                    inv_res = await db.execute(
                        select(UserInventoryItem).where(
                            and_(
                                UserInventoryItem.user_id == user.id,
                                UserInventoryItem.item_code == "rewind",
                            )
                        )
                    )
                    rewind_item = inv_res.scalar_one_or_none()
                    if rewind_item:
                        rewind_item.quantity += 3
                    else:
                        db.add(UserInventoryItem(user_id=user.id, item_code="rewind", quantity=3))
            elif prod_val == "credits_100":
                await add_user_credits(db, payment.user_id, 100, tx_type="donate", description="Пакет «Шпаргалка» (100 🎓)", reference_id=prod_val)
            elif prod_val == "credits_300":
                await add_user_credits(db, payment.user_id, 330, tx_type="donate", description="Пакет «Студенческий» (330 🎓)", reference_id=prod_val)
            elif prod_val == "credits_700":
                await add_user_credits(db, payment.user_id, 800, tx_type="donate", description="Пакет «Сессия закрыта» (800 🎓)", reference_id=prod_val)
            elif prod_val == "credits_1500":
                await add_user_credits(db, payment.user_id, 1800, tx_type="donate", description="Пакет «Красный диплом» (1800 🎓)", reference_id=prod_val)
            elif prod_val == "credits_3000":
                await add_user_credits(db, payment.user_id, 3800, tx_type="donate", description="Пакет «Грант ректора» (3800 🎓)", reference_id=prod_val)
            elif prod_val == "credits_6000":
                await add_user_credits(db, payment.user_id, 8000, tx_type="donate", description="Пакет «Кампусный инвестор» (8000 🎓)", reference_id=prod_val)
            elif payment.product == PaymentProduct.superlike_1:
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


async def check_user_can_buy_starter_pack(db: AsyncSession, user_id: int) -> bool:
    """Проверяет, может ли пользователь купить стартовый набор (не более 1 раза на аккаунт)."""
    user = await get_user(db, user_id)
    if not user:
        return False
    if getattr(user, "has_bought_starter_pack", False):
        return False

    res = await db.execute(
        select(func.count(Payment.id)).where(
            and_(
                Payment.user_id == user_id,
                Payment.product == PaymentProduct.starter_pack_99,
                Payment.status == PaymentStatus.succeeded,
            )
        )
    )
    count = res.scalar() or 0
    if count > 0:
        user.has_bought_starter_pack = True
        await db.commit()
        return False
    return True


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
    db: AsyncSession,
    user_id: int,
    limit: int = 30,
    mode: Optional[ModeEnum] = None,
) -> List[Swipe]:
    """
    Возвращает список входящих лайков/суперлайков для user_id от пользователей,
    которым user_id ещё не поставил ответный положительный свайп (like/superlike).
    """
    swiped_conds = [
        Swipe.from_user_id == user_id,
        Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
    ]
    if mode:
        swiped_conds.append(Swipe.mode == mode)

    swiped_subq = select(Swipe.to_user_id).where(and_(*swiped_conds))

    query_conds = [
        Swipe.to_user_id == user_id,
        Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
        User.is_active == True,
        Profile.is_visible == True,
        ~Swipe.from_user_id.in_(swiped_subq),
    ]
    if mode:
        query_conds.append(Swipe.mode == mode)

    result = await db.execute(
        select(Swipe)
        .options(
            selectinload(Swipe.from_user).selectinload(User.profile),
            selectinload(Swipe.from_user).selectinload(User.university),
        )
        .join(User, Swipe.from_user_id == User.id)
        .join(Profile, Profile.user_id == User.id)
        .where(and_(*query_conds))
        .order_by(
            case((Swipe.action == SwipeAction.superlike, 1), else_=0).desc(),
            Swipe.created_at.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_incoming_likes_count(
    db: AsyncSession,
    user_id: int,
    mode: Optional[ModeEnum] = None,
) -> int:
    """Количество непросмотренных входящих лайков."""
    swiped_conds = [
        Swipe.from_user_id == user_id,
        Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
    ]
    if mode:
        swiped_conds.append(Swipe.mode == mode)

    swiped_subq = select(Swipe.to_user_id).where(and_(*swiped_conds))

    query_conds = [
        Swipe.to_user_id == user_id,
        Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
        User.is_active == True,
        ~Swipe.from_user_id.in_(swiped_subq),
    ]
    if mode:
        query_conds.append(Swipe.mode == mode)

    result = await db.scalar(
        select(func.count(Swipe.id))
        .join(User, Swipe.from_user_id == User.id)
        .where(and_(*query_conds))
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
            .selectinload(User.university),
            selectinload(EmployerProfileAccess.profile)
            .selectinload(Profile.user)
            .selectinload(User.privacy),
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
    accesses = list(result.scalars().all())
    return [
        acc for acc in accesses
        if not (acc.profile and acc.profile.user and acc.profile.user.privacy and acc.profile.user.privacy.allow_employer_access is False)
    ]


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


# ─────────────────────────────────────────────────────────────
# Projects CRUD
# ─────────────────────────────────────────────────────────────
async def create_project(
    db: AsyncSession,
    user_id: int,
    title: str,
    pitch: str,
    description: str,
    stage: str = "idea",
    required_roles: Optional[List[str]] = None,
    conditions: Optional[str] = None,
    demo_url: Optional[str] = None,
    pitchdeck_url: Optional[str] = None,
    cover_url: Optional[str] = None,
) -> Project:
    project = Project(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title.strip(),
        pitch=pitch.strip(),
        description=description.strip(),
        stage=stage or "idea",
        required_roles=required_roles or [],
        conditions=conditions,
        demo_url=demo_url,
        pitchdeck_url=pitchdeck_url,
        cover_url=cover_url,
        is_active=True,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(db: AsyncSession, project_id: uuid.UUID) -> Optional[Project]:
    result = await db.execute(
        select(Project)
        .options(
            selectinload(Project.user).selectinload(User.profile),
            selectinload(Project.user).selectinload(User.university),
        )
        .where(Project.id == project_id)
    )
    return result.scalar_one_or_none()


async def get_user_projects(db: AsyncSession, user_id: int, only_active: bool = False) -> List[Project]:
    stmt = select(Project).where(Project.user_id == user_id)
    if only_active:
        stmt = stmt.where(Project.is_active.is_(True))
    stmt = stmt.order_by(Project.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: int,
    **kwargs,
) -> Optional[Project]:
    project = await get_project(db, project_id)
    if not project or project.user_id != user_id:
        return None
    for k, v in kwargs.items():
        if hasattr(project, k):
            setattr(project, k, v)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project_id: uuid.UUID, user_id: int) -> bool:
    project = await get_project(db, project_id)
    if not project or project.user_id != user_id:
        return False
    await db.delete(project)
    await db.commit()
    return True


async def get_projects_feed(
    db: AsyncSession,
    viewer_user_id: int,
    q: Optional[str] = None,
    stage: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    exclude_swiped: bool = True,
    exclude_own: bool = True,
) -> List[Project]:
    where_conditions = [Project.is_active.is_(True)]
    if exclude_own:
        where_conditions.append(Project.user_id != viewer_user_id)

    if exclude_swiped:
        swiped_stmt = select(Swipe.to_project_id).where(
            and_(
                Swipe.from_user_id == viewer_user_id,
                Swipe.to_project_id.isnot(None),
            )
        )
        swiped_res = await db.execute(swiped_stmt)
        swiped_project_ids = set(swiped_res.scalars().all())
        if swiped_project_ids:
            where_conditions.append(Project.id.not_in(swiped_project_ids))

    stmt = (
        select(Project)
        .options(
            selectinload(Project.user).selectinload(User.profile),
            selectinload(Project.user).selectinload(User.university),
        )
        .where(and_(*where_conditions))
    )

    if q and q.strip():
        q_term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Project.title.ilike(q_term),
                Project.pitch.ilike(q_term),
                Project.description.ilike(q_term),
            )
        )

    if stage and stage != "all":
        stmt = stmt.where(Project.stage == stage)

    stmt = stmt.order_by(Project.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    projects = list(result.scalars().all())

    if role and role != "all":
        role_lower = role.lower()
        projects = [
            p for p in projects
            if any(role_lower in (r or "").lower() for r in (p.required_roles or []))
        ]

    return projects


async def get_project_candidates(db: AsyncSession, project_id: uuid.UUID) -> List[Tuple[User, Swipe]]:
    """Студенты, которые лайкнули проект и ожидают решения фаундера."""
    stmt = (
        select(User, Swipe)
        .join(Swipe, Swipe.from_user_id == User.id)
        .options(selectinload(User.profile), selectinload(User.university))
        .where(
            and_(
                Swipe.to_project_id == project_id,
                Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
            )
        )
        .order_by(Swipe.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.all())


async def founder_swipe_candidate(
    db: AsyncSession,
    founder_id: int,
    candidate_id: int,
    project_id: uuid.UUID,
    action: SwipeAction,
) -> bool:
    """
    Фаундер свайпает кандидата. Если action in (like, superlike), создается мэтч по проекту!
    """
    now = datetime.now(timezone.utc)
    match_cond = and_(
        Swipe.from_user_id == founder_id,
        Swipe.to_user_id == candidate_id,
        Swipe.to_project_id == project_id,
        Swipe.mode == ModeEnum.projects,
    )
    existing_swipe = await db.scalar(select(Swipe).where(match_cond))
    if existing_swipe:
        existing_swipe.action = action
        existing_swipe.created_at = now
    else:
        try:
            async with db.begin_nested():
                db.add(
                    Swipe(
                        from_user_id=founder_id,
                        to_user_id=candidate_id,
                        to_project_id=project_id,
                        mode=ModeEnum.projects,
                        action=action,
                        created_at=now,
                    )
                )
                await db.flush()
        except IntegrityError:
            existing_swipe = await db.scalar(select(Swipe).where(match_cond))
            if existing_swipe:
                existing_swipe.action = action
                existing_swipe.created_at = now

    is_match = False
    if action in (SwipeAction.like, SwipeAction.superlike):
        match_stmt = select(Match).where(
            and_(
                Match.mode == ModeEnum.projects,
                Match.project_id == project_id,
                or_(
                    and_(Match.user1_id == founder_id, Match.user2_id == candidate_id),
                    and_(Match.user1_id == candidate_id, Match.user2_id == founder_id),
                ),
            )
        )
        existing_match = (await db.execute(match_stmt)).scalar_one_or_none()
        if not existing_match:
            new_match = Match(
                user1_id=founder_id,
                user2_id=candidate_id,
                mode=ModeEnum.projects,
                project_id=project_id,
                user1_tg_approved=True,
            )
            db.add(new_match)
            is_match = True

    await db.commit()
    return is_match


# ─────────────────────────────────────────────────────────────
# Внутренняя экономика: Баланс «Зачётов» 🎓 и Транзакции
# ─────────────────────────────────────────────────────────────
async def add_user_credits(
    db: AsyncSession,
    user_id: int,
    amount: int,
    tx_type: str,
    description: str,
    reference_id: Optional[str] = None,
) -> int:
    """
    Начисление «Зачётов» с записью в аудит-лог транзакций.
    Возвращает актуальный баланс пользователя.
    """
    if amount <= 0:
        res = await db.execute(select(User.credits_balance).where(User.id == user_id))
        return res.scalar_one_or_none() or 0

    # Атомарный инкремент
    result = await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credits_balance=User.credits_balance + amount)
        .returning(User.credits_balance)
    )
    new_balance = result.scalar_one_or_none()
    if new_balance is None:
        return 0

    tx = EconomyTransaction(
        user_id=user_id,
        amount=amount,
        balance_after=new_balance,
        tx_type=tx_type,
        reference_id=reference_id,
        description=description,
    )
    db.add(tx)
    await db.commit()
    return new_balance


async def spend_user_credits(
    db: AsyncSession,
    user_id: int,
    amount: int,
    tx_type: str,
    description: str,
    reference_id: Optional[str] = None,
) -> Tuple[bool, int]:
    """
    Атомарное списание «Зачётов».
    Возвращает (успех: bool, новый_баланс: int).
    Если средств недостаточно — списание не происходит, возвращается текущий баланс.
    """
    if amount <= 0:
        res = await db.execute(select(User.credits_balance).where(User.id == user_id))
        return True, res.scalar_one_or_none() or 0

    result = await db.execute(
        update(User)
        .where(and_(User.id == user_id, User.credits_balance >= amount))
        .values(credits_balance=User.credits_balance - amount)
        .returning(User.credits_balance)
    )
    new_balance = result.scalar_one_or_none()
    if new_balance is None:
        # Узнаем текущий баланс для информативного ответа
        res = await db.execute(select(User.credits_balance).where(User.id == user_id))
        current = res.scalar_one_or_none() or 0
        return False, current

    tx = EconomyTransaction(
        user_id=user_id,
        amount=-amount,
        balance_after=new_balance,
        tx_type=tx_type,
        reference_id=reference_id,
        description=description,
    )
    db.add(tx)
    await db.commit()
    return True, new_balance


async def get_user_credits_balance(db: AsyncSession, user_id: int) -> int:
    """Получить текущий баланс зачётов пользователя."""
    res = await db.execute(select(User.credits_balance).where(User.id == user_id))
    val = res.scalar_one_or_none()
    return val if val is not None else 0


async def get_user_transactions(
    db: AsyncSession,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> List[EconomyTransaction]:
    """Получить историю транзакций пользователя."""
    res = await db.execute(
        select(EconomyTransaction)
        .where(EconomyTransaction.user_id == user_id)
        .order_by(EconomyTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(res.scalars().all())


# ─────────────────────────────────────────────────────────────
# Ежедневные стрики посещаемости («Стипендия»)
# ─────────────────────────────────────────────────────────────
STREAK_REWARDS_MAP = {
    1: 4,
    2: 6,
    3: 8,
    4: 10,
    5: 12,
    6: 16,
    7: 24,
}


async def claim_daily_streak(db: AsyncSession, user_id: int) -> Tuple[bool, str, int, int]:
    """
    Забрать ежедневную «Стипендию» (стрик входа).
    Возвращает (success: bool, status_message: str, current_streak: int, reward_credits: int).
    """
    res = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = res.scalar_one_or_none()
    if not user:
        return False, "Пользователь не найден", 0, 0

    now = datetime.now(timezone.utc)
    today = now.date()

    used_freeze = False
    new_streak = 1

    if user.last_streak_date:
        last_date = user.last_streak_date.date()
        diff = (today - last_date).days

        if diff == 0:
            return False, "Ты уже забрал(а) стипендию за сегодня! Приходи завтра ⏳", user.streak_days, 0
        elif diff == 1:
            new_streak = (user.streak_days or 0) + 1
        elif diff == 2:
            # Пропущен 1 день — проверяем наличие заморозки стрика
            if (user.streak_freeze_count or 0) > 0:
                user.streak_freeze_count -= 1
                used_freeze = True
                new_streak = (user.streak_days or 0) + 1
            else:
                new_streak = 1
        else:
            # Пропущено 2+ дня — сброс серии
            new_streak = 1
    else:
        new_streak = 1

    # Расчет награды
    cycle_day = ((new_streak - 1) % 7) + 1
    reward = STREAK_REWARDS_MAP.get(cycle_day, 10)
    bonus_superlike = False

    if cycle_day == 7:
        user.superlike_balance = (user.superlike_balance or 0) + 1
        bonus_superlike = True

    user.streak_days = new_streak
    user.last_streak_date = now
    user.credits_balance = (user.credits_balance or 0) + reward

    desc = f"Стипендия за день {new_streak} стрика"
    if used_freeze:
        desc += " (спасён справкой от врача)"
    if bonus_superlike:
        desc += " + 1 Суперлайк за неделю!"

    tx = EconomyTransaction(
        user_id=user_id,
        amount=reward,
        balance_after=user.credits_balance,
        tx_type="streak",
        reference_id=f"streak_{new_streak}",
        description=desc,
    )
    db.add(tx)
    await db.commit()

    msg = f"🎓 <b>+{reward} Зачётов!</b>\n🔥 Серия входа: <b>{new_streak} дн.</b>"
    if used_freeze:
        msg = f"🩺 <i>«Справка от врача» спасла твою серию!</i>\n" + msg
    if bonus_superlike:
        msg += "\n🎉 <b>Неделя закрыта! Начислен +1 ⭐️ Суперлайк в подарок!</b>"

    return True, msg, new_streak, reward


# ─────────────────────────────────────────────────────────────
# Ежедневные задания (Дейлики)
# ─────────────────────────────────────────────────────────────
DEFAULT_DAILY_QUESTS_CONFIG = [
    {
        "key": "swipes_15",
        "title": "👀 Разведка в ленте",
        "description": "Просмотреть 15 анкет студентов",
        "target": 15,
        "reward": 6,
    },
    {
        "key": "likes_5",
        "title": "❤️ Первый шаг",
        "description": "Поставить 5 лайков или 1 суперлайк",
        "target": 5,
        "reward": 6,
    },
    {
        "key": "chat_1",
        "title": "💬 Студенческий контакт",
        "description": "Отправить сообщение взаимному мэтчу",
        "target": 1,
        "reward": 8,
    },
]


async def get_or_create_daily_quests(db: AsyncSession, user_id: int) -> List[UserDailyQuest]:
    """
    Возвращает актуальный список дейликов пользователя на сегодня (создаёт при отсутствии).
    Для пользователей с активным Премиумом награда умножается на 3 (x3 🎓).
    """
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    user = await get_user(db, user_id)
    multiplier = 3 if (user and user.is_premium) else 1

    # Ищем существующие квесты на сегодня
    res = await db.execute(
        select(UserDailyQuest).where(
            and_(
                UserDailyQuest.user_id == user_id,
                UserDailyQuest.quest_date == today_start,
            )
        )
    )
    existing_quests = {q.quest_key: q for q in res.scalars().all()}

    quests_list = []
    created_any = False
    for cfg in DEFAULT_DAILY_QUESTS_CONFIG:
        q_key = cfg["key"]
        expected_reward = cfg["reward"] * multiplier
        if q_key in existing_quests:
            eq = existing_quests[q_key]
            if not eq.is_claimed and eq.reward_credits != expected_reward:
                eq.reward_credits = expected_reward
                created_any = True
            quests_list.append(eq)
        else:
            new_q = UserDailyQuest(
                user_id=user_id,
                quest_date=today_start,
                quest_key=q_key,
                current_progress=0,
                target_progress=cfg["target"],
                reward_credits=expected_reward,
                is_claimed=False,
            )
            db.add(new_q)
            quests_list.append(new_q)
            created_any = True

    if created_any:
        await db.commit()

    return quests_list


async def track_daily_quest_event(
    db: AsyncSession,
    user_id: int,
    quest_key: str,
    increment: int = 1,
) -> Optional[UserDailyQuest]:
    """
    Инкрементирует прогресс конкретного дейлика пользователя на текущий день.
    """
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    res = await db.execute(
        select(UserDailyQuest).where(
            and_(
                UserDailyQuest.user_id == user_id,
                UserDailyQuest.quest_date == today_start,
                UserDailyQuest.quest_key == quest_key,
            )
        )
    )
    quest = res.scalar_one_or_none()
    if not quest:
        # Создаем если ещё нет
        cfg = next((c for c in DEFAULT_DAILY_QUESTS_CONFIG if c["key"] == quest_key), None)
        if not cfg:
            return None
        user = await get_user(db, user_id)
        multiplier = 3 if (user and user.is_premium) else 1
        quest = UserDailyQuest(
            user_id=user_id,
            quest_date=today_start,
            quest_key=quest_key,
            current_progress=0,
            target_progress=cfg["target"],
            reward_credits=cfg["reward"] * multiplier,
            is_claimed=False,
        )
        db.add(quest)

    if quest.current_progress < quest.target_progress:
        quest.current_progress = min(quest.target_progress, quest.current_progress + increment)
        await db.commit()

    return quest


async def claim_daily_quest(
    db: AsyncSession,
    user_id: int,
    quest_key: str,
) -> Tuple[bool, str, int]:
    """
    Забрать награду за выполненный дейлик (x3 для пользователей с Премиум).
    Возвращает (success: bool, message: str, reward_credits: int).
    """
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    res = await db.execute(
        select(UserDailyQuest).where(
            and_(
                UserDailyQuest.user_id == user_id,
                UserDailyQuest.quest_date == today_start,
                UserDailyQuest.quest_key == quest_key,
            )
        ).with_for_update()
    )
    quest = res.scalar_one_or_none()
    if not quest:
        return False, "Задание не найдено", 0

    if quest.is_claimed:
        return False, "Награда за это задание уже получена сегодня ✅", 0

    if quest.current_progress < quest.target_progress:
        return False, f"Задание ещё не выполнено ({quest.current_progress}/{quest.target_progress})", 0

    quest.is_claimed = True
    quest.claimed_at = now

    user = await get_user(db, user_id)
    is_premium = bool(user and user.is_premium)
    multiplier = 3 if is_premium else 1

    cfg = next((c for c in DEFAULT_DAILY_QUESTS_CONFIG if c["key"] == quest_key), None)
    base_reward = cfg["reward"] if cfg else quest.reward_credits
    reward = base_reward * multiplier
    quest.reward_credits = reward

    prem_suffix = " (👑 Премиум x3)" if is_premium else ""
    await add_user_credits(
        db,
        user_id=user_id,
        amount=reward,
        tx_type="quest",
        description=f"Награда за дейлик: {quest_key}{prem_suffix}",
        reference_id=quest_key,
    )
    prem_notice = " <i>(👑 Премиум x3!)</i>" if is_premium else ""
    return True, f"🎉 <b>+{reward} Зачётов начислено!{prem_notice}</b>", reward


# ─────────────────────────────────────────────────────────────
# Постоянные задания и Достижения кампуса (Permanent Quests)
# ─────────────────────────────────────────────────────────────
DEFAULT_PERMANENT_QUESTS_CONFIG = [
    {
        "key": "onboarding_profile",
        "title": "🎓 Академический профиль",
        "description": "Заполнить все ключевые разделы анкеты",
        "icon": "🎓",
        "target": 1,
        "reward_credits": 20,
        "reward_badge": None,
        "ref_check": ["onboarding_profile_complete"],
    },
    {
        "key": "onboarding_email",
        "title": "🏛 Студенческий статус",
        "description": "Подтвердить университетскую корпоративную почту",
        "icon": "🏛",
        "target": 1,
        "reward_credits": 40,
        "reward_badge": "Верифицирован 🎓",
        "ref_check": ["onboarding_email_verified"],
    },
    {
        "key": "onboarding_gallery",
        "title": "📸 Портфолио в сборе",
        "description": "Загрузить 3 или более фото в анкету",
        "icon": "📸",
        "target": 3,
        "reward_credits": 12,
        "reward_badge": None,
        "ref_check": ["onboarding_gallery_3_photos"],
    },
    {
        "key": "invite_friend_1",
        "title": "🤝 Кампусный нетворк",
        "description": "Пригласить 1 друга по реферальной ссылке",
        "icon": "🤝",
        "target": 1,
        "reward_credits": 20,
        "reward_badge": None,
        "ref_check": [],
    },
    {
        "key": "invite_friend_3",
        "title": "👥 Душа компании",
        "description": "Пригласить 3 друзей в StudMatch",
        "icon": "👥",
        "target": 3,
        "reward_credits": 60,
        "reward_badge": "Амбассадор 🌟",
        "ref_check": [],
    },
    {
        "key": "matches_5",
        "title": "💬 Первый коннект",
        "description": "Найти 5 взаимных симпатий в ленте знакомств",
        "icon": "❤️",
        "target": 5,
        "reward_credits": 16,
        "reward_badge": None,
        "ref_check": [],
    },
    {
        "key": "streak_7",
        "title": "🔥 Железная дисциплина",
        "description": "Собрать серию посещений 7 дней подряд",
        "icon": "🔥",
        "target": 7,
        "reward_credits": 40,
        "reward_badge": "Активист ⚡️",
        "ref_check": [],
    },
    {
        "key": "academic_diploma",
        "title": "📜 Отличник учёбы",
        "description": "Подтвердить академический диплом или олимпиаду",
        "icon": "📜",
        "target": 1,
        "reward_credits": 30,
        "reward_badge": "Отличник 🥇",
        "ref_check": [],
    },
    {
        "key": "gift_sent_1",
        "title": "🎁 Щедрая душа",
        "description": "Подарить 1 подарок другому студенту",
        "icon": "🎁",
        "target": 1,
        "reward_credits": 20,
        "reward_badge": "Меценат 🎁",
        "ref_check": [],
    },
    {
        "key": "gifts_received_3",
        "title": "👑 Любимчик кампуса",
        "description": "Получить 3 любых подарка в профиль",
        "icon": "👑",
        "target": 3,
        "reward_credits": 40,
        "reward_badge": "Звезда ⭐️",
        "ref_check": [],
    },
]


async def get_or_create_permanent_quests(db: AsyncSession, user_id: int) -> List[UserPermanentQuest]:
    """
    Возвращает актуальный список постоянных заданий студента с ретроспективным расчетом прогресса.
    """
    user = await get_user(db, user_id)
    if not user:
        return []

    # 1. Считаем фактический прогресс пользователя по базе
    p = user.profile
    profile_complete = 1 if (p and (p.is_complete or (p.goal and len(p.goal.strip()) > 3) or (p.name and len(p.name.strip()) > 1))) else 0
    email_verified = 1 if user.email_verified else 0

    photos_count = 0
    if p and p.photos:
        photos_count = len(p.photos)
    elif p and p.avatar_file_id:
        photos_count = 1

    ref_count = (await db.execute(select(func.count(User.id)).where(User.referrer_id == user_id))).scalar() or 0
    match_count = (await db.execute(select(func.count(Match.id)).where(or_(Match.user1_id == user_id, Match.user2_id == user_id)))).scalar() or 0
    streak_count = user.streak_days or 0
    ach_count = (await db.execute(select(func.count(Achievement.id)).where(and_(Achievement.user_id == user_id, Achievement.verified == VerifiedStatus.approved)))).scalar() or 0
    sent_gifts_count = (await db.execute(select(func.count(EconomyTransaction.id)).where(and_(EconomyTransaction.user_id == user_id, EconomyTransaction.tx_type == "gift")))).scalar() or 0
    received_gifts_count = (await db.execute(select(func.count(UserReceivedGift.id)).where(UserReceivedGift.recipient_id == user_id))).scalar() or 0

    # 2. Получаем историю транзакций, чтобы знать, какие награды уже выплачивались ранее
    tx_res = await db.execute(
        select(EconomyTransaction.reference_id).where(EconomyTransaction.user_id == user_id)
    )
    existing_tx_refs = {r for r in tx_res.scalars().all() if r}

    # 3. Получаем сохранённые записи UserPermanentQuest
    pq_res = await db.execute(
        select(UserPermanentQuest).where(UserPermanentQuest.user_id == user_id)
    )
    existing_quests = {q.quest_key: q for q in pq_res.scalars().all()}

    progress_map = {
        "onboarding_profile": min(1, profile_complete),
        "onboarding_email": min(1, email_verified),
        "onboarding_gallery": min(3, photos_count),
        "invite_friend_1": min(1, ref_count),
        "invite_friend_3": min(3, ref_count),
        "matches_5": min(5, match_count),
        "streak_7": min(7, streak_count),
        "academic_diploma": min(1, ach_count),
        "gift_sent_1": min(1, sent_gifts_count),
        "gifts_received_3": min(3, received_gifts_count),
    }

    result_list = []
    has_changes = False

    is_premium = bool(user and user.is_premium)
    multiplier = 3 if is_premium else 1

    for cfg in DEFAULT_PERMANENT_QUESTS_CONFIG:
        q_key = cfg["key"]
        calc_progress = progress_map.get(q_key, 0)
        target = cfg["target"]
        reward = cfg["reward_credits"] * multiplier
        badge = cfg.get("reward_badge")

        was_previously_rewarded = (
            f"perm_quest_{q_key}" in existing_tx_refs
            or any(ref in existing_tx_refs for ref in cfg.get("ref_check", []))
        )

        if q_key in existing_quests:
            quest = existing_quests[q_key]
            if calc_progress > quest.current_progress:
                quest.current_progress = calc_progress
                has_changes = True
            if not quest.is_claimed and quest.reward_credits != reward:
                quest.reward_credits = reward
                has_changes = True
            if not quest.is_claimed and was_previously_rewarded:
                quest.is_claimed = True
                has_changes = True
            result_list.append(quest)
        else:
            new_quest = UserPermanentQuest(
                user_id=user_id,
                quest_key=q_key,
                current_progress=calc_progress,
                target_progress=target,
                reward_credits=reward,
                reward_badge=badge,
                is_claimed=was_previously_rewarded,
                claimed_at=datetime.now(timezone.utc) if was_previously_rewarded else None,
            )
            db.add(new_quest)
            result_list.append(new_quest)
            has_changes = True

    if has_changes:
        try:
            await db.commit()
        except Exception as e:
            logger.warning("Error saving permanent quests: %s", e)
            await db.rollback()

    return result_list


async def claim_permanent_quest(
    db: AsyncSession,
    user_id: int,
    quest_key: str,
) -> Tuple[bool, str, int, Optional[str], int]:
    """
    Забрать награду за выполненное постоянное задание (x3 для пользователей с Премиум).
    Возвращает (success: bool, message: str, reward_credits: int, reward_badge: Optional[str], new_balance: int).
    """
    res = await db.execute(
        select(UserPermanentQuest).where(
            and_(
                UserPermanentQuest.user_id == user_id,
                UserPermanentQuest.quest_key == quest_key,
            )
        ).with_for_update()
    )
    quest = res.scalar_one_or_none()
    if not quest:
        return False, "Задание не найдено", 0, None, 0

    if quest.is_claimed:
        return False, "Награда за это задание уже получена ✅", 0, None, 0

    if quest.current_progress < quest.target_progress:
        return False, f"Задание ещё не выполнено ({quest.current_progress}/{quest.target_progress})", 0, None, 0

    quest.is_claimed = True
    quest.claimed_at = datetime.now(timezone.utc)

    user = await get_user(db, user_id)
    is_premium = bool(user and user.is_premium)
    multiplier = 3 if is_premium else 1

    cfg = next((c for c in DEFAULT_PERMANENT_QUESTS_CONFIG if c["key"] == quest_key), None)
    base_reward = cfg["reward_credits"] if cfg else (quest.reward_credits or 0)
    reward = base_reward * multiplier
    quest.reward_credits = reward
    badge = quest.reward_badge
    ref_id = f"perm_quest_{quest_key}"

    prem_suffix = " (👑 Премиум x3)" if is_premium else ""
    new_bal = await add_user_credits(
        db,
        user_id=user_id,
        amount=reward,
        tx_type="quest",
        description=f"Награда за достижение: {quest_key}{prem_suffix}",
        reference_id=ref_id,
    )

    prem_notice = " <i>(👑 Премиум x3!)</i>" if is_premium else ""
    msg = f"🎉 <b>+{reward} Зачётов начислено!{prem_notice}</b>"
    if badge:
        msg += f"\n🏆 <i>Разблокирован титул: {badge}</i>"

    return True, msg, reward, badge, new_bal


async def track_permanent_quest_event(
    db: AsyncSession,
    user_id: int,
    quest_key: str,
    increment: int = 1,
) -> Optional[UserPermanentQuest]:
    """
    Инкрементирует прогресс постоянного задания пользователя.
    """
    res = await db.execute(
        select(UserPermanentQuest).where(
            and_(
                UserPermanentQuest.user_id == user_id,
                UserPermanentQuest.quest_key == quest_key,
            )
        )
    )
    quest = res.scalar_one_or_none()
    if not quest:
        cfg = next((c for c in DEFAULT_PERMANENT_QUESTS_CONFIG if c["key"] == quest_key), None)
        if not cfg:
            return None
        quest = UserPermanentQuest(
            user_id=user_id,
            quest_key=quest_key,
            current_progress=min(cfg["target"], increment),
            target_progress=cfg["target"],
            reward_credits=cfg["reward_credits"],
            reward_badge=cfg.get("reward_badge"),
        )
        db.add(quest)
        await db.commit()
        return quest

    if quest.current_progress < quest.target_progress:
        quest.current_progress = min(quest.target_progress, quest.current_progress + increment)
        await db.commit()

    return quest


# ─────────────────────────────────────────────────────────────
# Каталог магазина и покупки
# ─────────────────────────────────────────────────────────────
async def get_shop_catalog(
    db: AsyncSession,
    category: Optional[str] = None,
    only_active: bool = True,
) -> List[ShopItem]:
    """Получить список товаров магазина, отсортированных по sort_order."""
    stmt = select(ShopItem)
    if only_active:
        stmt = stmt.where(ShopItem.is_active == True)
    if category:
        stmt = stmt.where(ShopItem.category == category)
    stmt = stmt.order_by(ShopItem.sort_order.asc(), ShopItem.id.asc())

    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_shop_item(db: AsyncSession, item_code: str) -> Optional[ShopItem]:
    """Получить товар магазина по уникальному коду."""
    res = await db.execute(select(ShopItem).where(ShopItem.code == item_code))
    return res.scalar_one_or_none()


async def buy_shop_item_with_credits(
    db: AsyncSession,
    user_id: int,
    item_code: str,
) -> Tuple[bool, str]:
    """
    Покупка товара магазина за «Зачёты» 🎓.
    Атомарно списывает валюту и начисляет купленный бонус/предмет.
    """
    item = await get_shop_item(db, item_code)
    if not item or not item.is_active:
        return False, "❌ Товар не найден или временно недоступен."

    user = await get_user(db, user_id)
    if not user:
        return False, "Пользователь не найден."

    if (user.credits_balance or 0) < item.price_credits:
        diff = item.price_credits - (user.credits_balance or 0)
        return False, f"⚠️ Недостаточно зачётов. Не хватает: <b>{diff} 🎓</b>."

    # Списываем зачёты
    success, new_bal = await spend_user_credits(
        db,
        user_id=user_id,
        amount=item.price_credits,
        tx_type="purchase",
        description=f"Покупка товара: {item.title}",
        reference_id=item.code,
    )
    if not success:
        return False, "⚠️ Не удалось списать зачёты. Попробуй позже."

    # Начисляем купленный товар
    now = datetime.now(timezone.utc)
    b_type = item.bonus_type
    b_val = item.bonus_value or 1

    reward_text = item.title

    if b_type == "superlike":
        user.superlike_balance = (user.superlike_balance or 0) + b_val

    elif b_type == "rewind":
        # Добавляем в инвентарь количество шпор/откатов
        inv_res = await db.execute(
            select(UserInventoryItem).where(
                and_(UserInventoryItem.user_id == user_id, UserInventoryItem.item_code == "rewind")
            )
        )
        inv_item = inv_res.scalar_one_or_none()
        if inv_item:
            inv_item.quantity += b_val
        else:
            db.add(UserInventoryItem(user_id=user_id, item_code="rewind", quantity=b_val))

    elif b_type == "freeze":
        user.streak_freeze_count = (user.streak_freeze_count or 0) + b_val

    elif b_type == "boost":
        hours = b_val
        base_time = user.boost_until if user.boost_until and user.boost_until > now else now
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)
        user.boost_until = base_time + timedelta(hours=hours)

    elif b_type == "premium":
        days = b_val
        base_time = user.premium_until if user.premium_until and user.premium_until > now else now
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)
        user.premium_until = base_time + timedelta(days=days)

    elif b_type == "frame":
        duration = item.duration_days or 30
        exp_at = now + timedelta(days=duration)
        # Добавляем или продлеваем рамку в инвентаре
        inv_res = await db.execute(
            select(UserInventoryItem).where(
                and_(UserInventoryItem.user_id == user_id, UserInventoryItem.item_code == item.code)
            )
        )
        inv_item = inv_res.scalar_one_or_none()
        if inv_item:
            base_exp = inv_item.expires_at if inv_item.expires_at and inv_item.expires_at > now else now
            inv_item.expires_at = base_exp + timedelta(days=duration)
            inv_item.is_equipped = True
        else:
            db.add(
                UserInventoryItem(
                    user_id=user_id,
                    item_code=item.code,
                    quantity=1,
                    expires_at=exp_at,
                    is_equipped=True,
                )
            )
        # Автоматически надеваем рамку
        user.equipped_frame = item.code

    await db.commit()
    return True, f"🎉 <b>Успешно куплено: {reward_text}!</b>\nОстаток на балансе: <b>{new_bal} 🎓</b>"


# ─────────────────────────────────────────────────────────────
# Инвентарь и Откат свайпа («Шпора»)
# ─────────────────────────────────────────────────────────────
async def get_user_inventory(db: AsyncSession, user_id: int) -> List[UserInventoryItem]:
    """Получить предметы из инвентаря пользователя."""
    res = await db.execute(
        select(UserInventoryItem).where(UserInventoryItem.user_id == user_id)
    )
    return list(res.scalars().all())


async def equip_profile_frame(db: AsyncSession, user_id: int, frame_code: Optional[str]) -> bool:
    """Надеть или снять рамку профиля."""
    user = await get_user(db, user_id)
    if not user:
        return False

    if frame_code is None or frame_code == "none":
        user.equipped_frame = None
        await db.commit()
        return True

    # Проверяем наличие активной рамки в инвентаре
    now = datetime.now(timezone.utc)
    res = await db.execute(
        select(UserInventoryItem).where(
            and_(
                UserInventoryItem.user_id == user_id,
                UserInventoryItem.item_code == frame_code,
            )
        )
    )
    inv_item = res.scalar_one_or_none()
    if not inv_item:
        return False

    if inv_item.expires_at:
        exp = inv_item.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            return False

    user.equipped_frame = frame_code
    await db.commit()
    return True


async def rewind_last_swipe(db: AsyncSession, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """
    Откат последнего свайпа («Шпора» 🔄).
    Списывает 1 предмет 'rewind' из инвентаря и удаляет последний свайп (skip/like).
    Возвращает (success: bool, message: str, reverted_user_id: Optional[int]).
    """
    # 1. Проверяем наличие 'rewind' в инвентаре
    res = await db.execute(
        select(UserInventoryItem).where(
            and_(
                UserInventoryItem.user_id == user_id,
                UserInventoryItem.item_code == "rewind",
                UserInventoryItem.quantity > 0,
            )
        )
    )
    inv_item = res.scalar_one_or_none()
    if not inv_item:
        return False, "❌ У тебя нет «Шпоры» (отката свайпа). Приобрети её в Магазине за 10 🎓!", None

    # 2. Ищем последний свайп
    swipe_res = await db.execute(
        select(Swipe)
        .where(Swipe.from_user_id == user_id)
        .order_by(Swipe.created_at.desc())
        .limit(1)
    )
    last_swipe = swipe_res.scalar_one_or_none()
    if not last_swipe:
        return False, "ℹ️ Нет предыдущих свайпов для отмены.", None

    reverted_target_id = last_swipe.to_user_id

    # 3. Списываем 1 штуку
    inv_item.quantity -= 1
    if inv_item.quantity <= 0:
        await db.delete(inv_item)

    # 4. Удаляем последний свайп
    await db.delete(last_swipe)
    await db.commit()

    return True, "🔄 <b>Свайп успешно отменён!</b> Анкета возвращена в просмотр.", reverted_target_id


def get_gift_image_url(gift_code: str) -> str:
    """Возвращает URL реального веб-изображения подарка Telegram."""
    aliases = {
        "gift_coffee": "gift_bear",
        "gift_pizza": "gift_cake",
        "gift_flowers": "gift_bouquet",
        "gift_avtozachet": "gift_trophy",
        "gift_diamond": "gift_gem",
        "gift_heart_box": "gift_valentine_box",
    }
    code = aliases.get(gift_code, gift_code)
    return f"/static/webapp/gifts/{code}.webp"


# ─────────────────────────────────────────────────────────────
# Подарки Telegram (Telegram Classic & Collectible Gifts)
# ─────────────────────────────────────────────────────────────
DEFAULT_CAMPUS_GIFTS = [
    # ── 11 Классических неколлекционных подарков Telegram ──
    {
        "code": "gift_heart",
        "title": "Сердце (Heart)",
        "icon": "💝",
        "image_url": "/static/webapp/gifts/gift_heart.webp",
        "price_credits": 15,
        "exchange_credits": 12,
        "description": "Классическое розовое сияющее сердце Telegram — тёплый знак внимания.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_bear",
        "title": "Плюшевый мишка (Toy Bear)",
        "icon": "🧸",
        "image_url": "/static/webapp/gifts/gift_bear.webp",
        "price_credits": 15,
        "exchange_credits": 12,
        "description": "Официальный плюшевый мишка Telegram — тепло, забота и уют.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_box",
        "title": "Коробка подарка (Gift Box)",
        "icon": "🎁",
        "image_url": "/static/webapp/gifts/gift_box.webp",
        "price_credits": 25,
        "exchange_credits": 20,
        "description": "Праздничная коробка с лентой — универсальный сюрприз для любого повода.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_rose",
        "title": "Красная роза (Red Rose)",
        "icon": "🌹",
        "image_url": "/static/webapp/gifts/gift_rose.webp",
        "price_credits": 25,
        "exchange_credits": 20,
        "description": "Элегантная красная роза — символ романтической симпатии.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_cake",
        "title": "Праздничный торт (Cake)",
        "icon": "🎂",
        "image_url": "/static/webapp/gifts/gift_cake.webp",
        "price_credits": 50,
        "exchange_credits": 40,
        "description": "Праздничный торт с клубникой и тремя свечами из Telegram.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_bouquet",
        "title": "Букет тюльпанов (Bouquet)",
        "icon": "💐",
        "image_url": "/static/webapp/gifts/gift_bouquet.webp",
        "price_credits": 50,
        "exchange_credits": 40,
        "description": "Нежный букет весенних тюльпанов из Telegram.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_rocket",
        "title": "Космическая ракета (Rocket)",
        "icon": "🚀",
        "image_url": "/static/webapp/gifts/gift_rocket.webp",
        "price_credits": 50,
        "exchange_credits": 40,
        "description": "Стремительная ракета в полёте с огненным соплом из Telegram.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_trophy",
        "title": "Золотой кубок (Golden Trophy)",
        "icon": "🏆",
        "image_url": "/static/webapp/gifts/gift_trophy.webp",
        "price_credits": 100,
        "exchange_credits": 80,
        "description": "Золотой кубок победителя из Telegram.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_ring",
        "title": "Кольцо с бриллиантом (Diamond Ring)",
        "icon": "💍",
        "image_url": "/static/webapp/gifts/gift_ring.webp",
        "price_credits": 100,
        "exchange_credits": 80,
        "description": "Драгоценное кольцо с бриллиантом чистейшей огранки из Telegram.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_champagne",
        "title": "Шампанское (Holiday Drink)",
        "icon": "🍾",
        "image_url": "/static/webapp/gifts/gift_champagne.webp",
        "price_credits": 50,
        "exchange_credits": 40,
        "description": "Игристый праздничный напиток в честь долгожданного знакомства.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },
    {
        "code": "gift_gem",
        "title": "Кристалл (Ion Gem)",
        "icon": "💎",
        "image_url": "/static/webapp/gifts/gift_gem.webp",
        "price_credits": 100,
        "exchange_credits": 80,
        "description": "Сияющий драгоценный сапфир из коллекции редких Telegram-самоцветов.",
        "category": "telegram_classic",
        "badge": "⭐ Классика",
        "is_collectible": False,
    },

    # ── 4 Коллекционных редких подарка Telegram (NFT) ──
    {
        "code": "gift_lollipop",
        "title": "Леденец Lol Pop",
        "icon": "🍭",
        "image_url": "/static/webapp/gifts/gift_lollipop.webp",
        "price_credits": 2000,
        "exchange_credits": 1600,
        "description": "Коллекционный артефакт Lol Pop — эксклюзивная сладость.",
        "category": "telegram_collectible",
        "badge": "💎 NFT / Редкий",
        "is_collectible": True,
    },
    {
        "code": "gift_lush_bouquet",
        "title": "Lush Bouquet",
        "icon": "💐",
        "image_url": "/static/webapp/gifts/gift_lush_bouquet.webp",
        "price_credits": 2000,
        "exchange_credits": 1600,
        "description": "Премиальный коллекционный букет из ограниченного тиража Telegram.",
        "category": "telegram_collectible",
        "badge": "💎 NFT / Редкий",
        "is_collectible": True,
    },
    {
        "code": "gift_stellar_rocket",
        "title": "Звёздная ракета (Stellar Rocket)",
        "icon": "🚀",
        "image_url": "/static/webapp/gifts/gift_stellar_rocket.webp",
        "price_credits": 2000,
        "exchange_credits": 1600,
        "description": "Редкий коллекционный раритет Telegram. Космический статус для лучших.",
        "category": "telegram_collectible",
        "badge": "💎 NFT / Редкий",
        "is_collectible": True,
    },
    {
        "code": "gift_valentine_box",
        "title": "Valentine Box",
        "icon": "💝",
        "image_url": "/static/webapp/gifts/gift_valentine_box.webp",
        "price_credits": 5000,
        "exchange_credits": 4000,
        "description": "Редкая коллекционная шкатулка чувств — высший знак признания.",
        "category": "telegram_collectible",
        "badge": "💎 NFT / Редкий",
        "is_collectible": True,
    },
]

LEGACY_GIFTS_MAP = {
    "gift_heart_box": {"code": "gift_heart_box", "title": "Валентинка (Valentine Box)", "icon": "💝", "price_credits": 25, "exchange_credits": 20, "category": "telegram_classic", "is_collectible": False},
    "gift_coffee": {"code": "gift_coffee", "title": "«Кофе на перерыве»", "icon": "☕️", "price_credits": 15, "exchange_credits": 12, "category": "drink", "is_collectible": False},
    "gift_pizza": {"code": "gift_pizza", "title": "«Кусочек пиццы»", "icon": "🍕", "price_credits": 25, "exchange_credits": 20, "category": "food", "is_collectible": False},
    "gift_flowers": {"code": "gift_flowers", "title": "Букет роз", "icon": "💐", "price_credits": 25, "exchange_credits": 20, "category": "telegram_classic", "is_collectible": False},
    "gift_avtozachet": {"code": "gift_avtozachet", "title": "Золотой кубок", "icon": "🏆", "price_credits": 100, "exchange_credits": 85, "category": "telegram_classic", "is_collectible": False},
    "gift_diamond": {"code": "gift_diamond", "title": "Ионный кристалл", "icon": "💎", "price_credits": 100, "exchange_credits": 85, "category": "telegram_classic", "is_collectible": False},
    "gift_crown": {"code": "gift_crown", "title": "Цилиндр аристократа", "icon": "🎩", "price_credits": 2000, "exchange_credits": 1600, "category": "telegram_collectible", "is_collectible": True},
    "gift_duck": {"code": "gift_duck", "title": "Плюшевый Пепе", "icon": "🐸", "price_credits": 2000, "exchange_credits": 1600, "category": "telegram_collectible", "is_collectible": True},
}


async def get_campus_gifts_catalog(db: Optional[AsyncSession] = None) -> List[dict]:
    """Возвращает каталог подарков Telegram."""
    return DEFAULT_CAMPUS_GIFTS


async def send_campus_gift(
    db: AsyncSession,
    sender_id: int,
    recipient_id: int,
    gift_code: str,
    message: Optional[str] = None,
    is_anonymous: bool = False,
) -> Tuple[bool, str, Optional[UserReceivedGift]]:
    """
    Отправить подарок другому студенту за «Зачёты» 🎓.
    Списывает валюту с отправителя и сохраняет подарок получателю.
    """
    if sender_id == recipient_id:
        return False, "Нельзя отправлять подарки самому себе.", None

    gift_meta = next((g for g in DEFAULT_CAMPUS_GIFTS if g["code"] == gift_code), None) or LEGACY_GIFTS_MAP.get(gift_code)
    if not gift_meta:
        return False, "Подарок не найден в каталоге.", None

    sender = await get_user(db, sender_id)
    if not sender:
        return False, "Отправитель не найден.", None

    recipient = await get_user(db, recipient_id)
    if not recipient:
        return False, "Получатель подарка не найден.", None

    # 1. Проверяем, есть ли подарок в личном инвентаре пользователя
    inv_res = await db.execute(
        select(UserInventoryItem).where(
            and_(
                UserInventoryItem.user_id == sender_id,
                UserInventoryItem.item_code == gift_code,
                UserInventoryItem.quantity > 0,
            )
        ).with_for_update()
    )
    inv_item = inv_res.scalars().first()

    used_inventory = False
    if inv_item:
        inv_item.quantity -= 1
        if inv_item.quantity <= 0:
            await db.delete(inv_item)
        used_inventory = True
    else:
        price = gift_meta["price_credits"]
        if (sender.credits_balance or 0) < price:
            diff = price - (sender.credits_balance or 0)
            return False, f"Недостаточно зачётов. Не хватает: {diff} 🎓.", None

        # Списываем зачёты с отправителя
        success, _ = await spend_user_credits(
            db,
            user_id=sender_id,
            amount=price,
            tx_type="gift",
            description=f"Отправка подарка: {gift_meta['title']}",
            reference_id=gift_code,
        )
        if not success:
            return False, "Не удалось списать зачёты. Попробуйте позже.", None

    # Создаём запись полученного подарка
    gift_record = UserReceivedGift(
        sender_id=None if is_anonymous else sender_id,
        recipient_id=recipient_id,
        gift_code=gift_code,
        gift_title=gift_meta["title"],
        gift_icon=gift_meta["icon"],
        message=(message or "").strip()[:200] if message else None,
        is_anonymous=is_anonymous,
        is_pinned=False,
    )
    db.add(gift_record)
    await db.commit()
    await db.refresh(gift_record)

    # Прогресс постоянных заданий
    try:
        await track_permanent_quest_event(db, sender_id, "gift_sent_1", 1)
        await track_permanent_quest_event(db, recipient_id, "gifts_received_3", 1)
    except Exception as e:
        logger.warning(f"Failed to track gift quests: {e}")

    # Создаём карточку подарка во внутреннем чате, если мэтч уже существует
    try:
        import json
        match_res = await db.execute(
            select(Match).where(
                or_(
                    and_(Match.user1_id == sender_id, Match.user2_id == recipient_id),
                    and_(Match.user1_id == recipient_id, Match.user2_id == sender_id),
                )
            )
        )
        match = match_res.scalar_one_or_none()
        if match:
            sender_name = "Скрытый отправитель 🤫" if is_anonymous else (
                sender.profile.name if (sender.profile and sender.profile.name) else (sender.first_name or "Студент")
            )
            chat_payload = {
                "gift_code": gift_code,
                "gift_title": gift_meta["title"],
                "gift_icon": gift_meta["icon"],
                "image_url": get_gift_image_url(gift_code),
                "message": (message or "").strip()[:200] if message else None,
                "is_anonymous": is_anonymous,
                "sender_name": sender_name,
            }
            await create_chat_message(
                db,
                match_id=match.id,
                sender_id=sender_id,
                text=json.dumps(chat_payload, ensure_ascii=False),
                msg_type="gift",
            )
    except Exception as e:
        logger.warning(f"Failed to post gift card in match chat: {e}")

    return True, f"🎁 Подарок «{gift_meta['title']}» успешно отправлен!", gift_record


async def get_user_received_gifts(db: AsyncSession, user_id: int) -> List[UserReceivedGift]:
    """Получить список полученных подарков пользователя."""
    res = await db.execute(
        select(UserReceivedGift)
        .options(selectinload(UserReceivedGift.sender).selectinload(User.profile))
        .where(UserReceivedGift.recipient_id == user_id)
        .order_by(UserReceivedGift.is_pinned.desc(), UserReceivedGift.created_at.desc())
    )
    return list(res.scalars().all())


async def toggle_pin_user_gift(db: AsyncSession, user_id: int, gift_id: Any) -> Tuple[bool, str, bool]:
    """Закрепить или открепить подарок в профиле (макс. 3 закрепленных)."""
    if isinstance(gift_id, str):
        try:
            gift_id = uuid.UUID(gift_id)
        except Exception:
            return False, "Неверный идентификатор подарка.", False

    res = await db.execute(
        select(UserReceivedGift).where(
            and_(UserReceivedGift.id == gift_id, UserReceivedGift.recipient_id == user_id)
        )
    )
    gift = res.scalar_one_or_none()
    if not gift:
        return False, "Подарок не найден.", False

    if not gift.is_pinned:
        count_res = await db.execute(
            select(func.count(UserReceivedGift.id)).where(
                and_(UserReceivedGift.recipient_id == user_id, UserReceivedGift.is_pinned == True)
            )
        )
        pinned_count = count_res.scalar() or 0
        if pinned_count >= 3:
            return False, "Можно закрепить не более 3 подарков в профиле.", False
        gift.is_pinned = True
        msg = "Подарок закреплён в витрине профиля! ✨"
    else:
        gift.is_pinned = False
        msg = "Подарок откреплён."

    await db.commit()
    return True, msg, gift.is_pinned


async def convert_user_gift_to_credits(
    db: AsyncSession,
    user_id: int,
    gift_id: Any,
) -> Tuple[bool, str, int]:
    """
    Обменять полученный подарок на зачёты 🎓 (кэшаут 80-85%).
    Закреплённые подарки конвертировать нельзя (их сначала нужно открепить).
    """
    if isinstance(gift_id, str):
        try:
            gift_id = uuid.UUID(gift_id)
        except Exception:
            return False, "Неверный идентификатор подарка.", 0

    res = await db.execute(
        select(UserReceivedGift).where(
            and_(UserReceivedGift.id == gift_id, UserReceivedGift.recipient_id == user_id)
        ).with_for_update()
    )
    gift = res.scalar_one_or_none()
    if not gift:
        return False, "Подарок не найден в вашем профиле.", 0

    if gift.is_pinned:
        return False, "Нельзя обменять закреплённый подарок. Сначала открепите его из витрины.", 0

    gift_meta = next((g for g in DEFAULT_CAMPUS_GIFTS if g["code"] == gift.gift_code), None) or LEGACY_GIFTS_MAP.get(gift.gift_code)
    if gift_meta and "exchange_credits" in gift_meta:
        exchange_amount = gift_meta["exchange_credits"]
    elif gift_meta and "price_credits" in gift_meta:
        exchange_amount = max(10, int(gift_meta["price_credits"] * 0.8))
    else:
        exchange_amount = 20

    # Начисляем зачёты за конвертацию
    await add_user_credits(
        db,
        user_id=user_id,
        amount=exchange_amount,
        tx_type="gift_convert",
        description=f"Обмен подарка: {gift.gift_title}",
        reference_id=str(gift.id),
    )

    # Удаляем подарок из профиля
    await db.delete(gift)
    await db.commit()

    return True, f"Подарок «{gift.gift_title}» успешно обменян на +{exchange_amount} 🎓!", exchange_amount


# ─────────────────────────────────────────────────────────────
# Колесо Фортуны («Счастливый билет» 🎲)
# ─────────────────────────────────────────────────────────────
FORTUNE_WHEEL_SECTORS = [
    {"id": 0, "code": "credits_15", "icon": "🎓", "title": "+15 Зачётов", "type": "credits", "value": 15, "weight": 28, "color": "#3B82F6"},
    {"id": 1, "code": "credits_35", "icon": "🎓", "title": "+35 Зачётов", "type": "credits", "value": 35, "weight": 22, "color": "#F59E0B"},
    {"id": 2, "code": "rewind", "icon": "🔄", "title": "1 «Шпора»", "type": "item", "item_code": "rewind", "weight": 16, "color": "#8B5CF6"},
    {"id": 3, "code": "credits_75", "icon": "💰", "title": "+75 Зачётов", "type": "credits", "value": 75, "weight": 8, "color": "#EF4444"},
    {"id": 4, "code": "superlike", "icon": "⭐️", "title": "1 Суперлайк", "type": "superlike", "value": 1, "weight": 10, "color": "#EC4899"},
    {"id": 5, "code": "boost_6h", "icon": "⚡️", "title": "Буст 6 часов", "type": "boost", "value": 6, "weight": 6, "color": "#F97316"},
    {"id": 6, "code": "freeze", "icon": "🩺", "title": "1 «Справка»", "type": "freeze", "value": 1, "weight": 6, "color": "#10B981"},
    {"id": 7, "code": "gift_stellar_rocket", "icon": "🚀", "title": "Звёздная ракета", "type": "gift_item", "gift_code": "gift_stellar_rocket", "weight": 4, "color": "#6366F1"},
]

FORTUNE_PAID_SPIN_PRICE = 15  # Зачётов за платное вращение


async def get_fortune_wheel_status(db: AsyncSession, user_id: int) -> dict:
    """Проверяет доступность вращения Колеса Фортуны для студента."""
    user = await get_user(db, user_id)
    if not user:
        return {
            "can_spin_free": False,
            "seconds_left": 86400,
            "paid_price": FORTUNE_PAID_SPIN_PRICE,
            "sectors": FORTUNE_WHEEL_SECTORS,
        }

    now = datetime.now(timezone.utc)
    last_spin = user.last_fortune_spin_at
    if last_spin and last_spin.tzinfo is None:
        last_spin = last_spin.replace(tzinfo=timezone.utc)

    can_spin_free = False
    seconds_left = 0

    if not last_spin:
        can_spin_free = True
    else:
        diff_sec = (now - last_spin).total_seconds()
        if diff_sec >= 86400:
            can_spin_free = True
        else:
            seconds_left = int(86400 - diff_sec)

    return {
        "can_spin_free": can_spin_free,
        "seconds_left": max(0, seconds_left),
        "paid_price": FORTUNE_PAID_SPIN_PRICE,
        "credits_balance": user.credits_balance or 0,
        "can_spin_paid": (user.credits_balance or 0) >= FORTUNE_PAID_SPIN_PRICE,
        "spins_count": user.fortune_spins_count or 0,
        "sectors": [
            {
                "id": s["id"],
                "code": s["code"],
                "icon": s["icon"],
                "title": s["title"],
                "color": s["color"],
            }
            for s in FORTUNE_WHEEL_SECTORS
        ],
    }


async def spin_fortune_wheel(
    db: AsyncSession,
    user_id: int,
    use_paid: bool = False,
) -> Tuple[bool, str, Optional[dict]]:
    """
    Вращение Колеса Фортуны.
    Списывает валюту (если платно) или фиксирует дату (если бесплатно).
    Выдаёт выигранный приз и возвращает данные сектора.
    """
    res = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = res.scalar_one_or_none()
    if not user:
        return False, "Пользователь не найден.", None

    now = datetime.now(timezone.utc)
    last_spin = user.last_fortune_spin_at
    if last_spin and last_spin.tzinfo is None:
        last_spin = last_spin.replace(tzinfo=timezone.utc)

    is_free = False
    if not use_paid:
        if not last_spin or (now - last_spin).total_seconds() >= 86400:
            is_free = True
        else:
            return False, "Бесплатное вращение ещё не доступно. Попробуйте платное вращение за 15 🎓!", None
    else:
        if (user.credits_balance or 0) < FORTUNE_PAID_SPIN_PRICE:
            return False, f"Недостаточно зачётов для вращения (требуется {FORTUNE_PAID_SPIN_PRICE} 🎓).", None
        ok_spend, _ = await spend_user_credits(
            db,
            user_id=user_id,
            amount=FORTUNE_PAID_SPIN_PRICE,
            tx_type="wheel_spin",
            description="Вращение Колеса Фортуны 🎲",
        )
        if not ok_spend:
            return False, "Не удалось списать зачёты за вращение.", None

    if is_free:
        user.last_fortune_spin_at = now

    user.fortune_spins_count = (user.fortune_spins_count or 0) + 1

    import secrets
    # Случайный сектор с учётом весов (CSPRNG)
    weights = [s["weight"] for s in FORTUNE_WHEEL_SECTORS]
    chosen_sector = secrets.SystemRandom().choices(FORTUNE_WHEEL_SECTORS, weights=weights, k=1)[0]

    # Начисляем награду
    r_type = chosen_sector["type"]

    if r_type == "credits":
        await add_user_credits(
            db,
            user_id=user_id,
            amount=chosen_sector["value"],
            tx_type="wheel_win",
            description=f"Приз в Колесе Фортуны: {chosen_sector['title']}",
        )
    elif r_type == "item":
        item_code = chosen_sector["item_code"]
        res = await db.execute(
            select(UserInventoryItem).where(
                and_(UserInventoryItem.user_id == user_id, UserInventoryItem.item_code == item_code)
            )
        )
        inv_item = res.scalar_one_or_none()
        if inv_item:
            inv_item.quantity += 1
        else:
            db.add(UserInventoryItem(user_id=user_id, item_code=item_code, quantity=1))
    elif r_type == "superlike":
        user.superlike_balance = (user.superlike_balance or 0) + chosen_sector["value"]
    elif r_type == "boost":
        base_boost = user.boost_until if user.boost_until and user.boost_until > now else now
        user.boost_until = base_boost + timedelta(hours=chosen_sector["value"])
    elif r_type == "freeze":
        user.streak_freeze_count = (user.streak_freeze_count or 0) + chosen_sector["value"]
    elif r_type == "gift_item":
        gift_code = chosen_sector["gift_code"]
        res = await db.execute(
            select(UserInventoryItem).where(
                and_(UserInventoryItem.user_id == user_id, UserInventoryItem.item_code == gift_code)
            )
        )
        inv_item = res.scalar_one_or_none()
        if inv_item:
            inv_item.quantity += 1
        else:
            db.add(UserInventoryItem(user_id=user_id, item_code=gift_code, quantity=1))

        # Также добавляем в коллекцию полученных подарков на витрину профиля
        db.add(
            UserReceivedGift(
                sender_id=None,
                recipient_id=user_id,
                gift_code=gift_code,
                gift_title=chosen_sector["title"],
                gift_icon=chosen_sector["icon"],
                message="Выиграно в Колесе Фортуны! 🎰✨",
                is_anonymous=False,
                is_pinned=False,
            )
        )

    await db.commit()
    await db.refresh(user)

    result_data = {
        "sector_id": chosen_sector["id"],
        "sector_code": chosen_sector["code"],
        "sector_title": chosen_sector["title"],
        "sector_icon": chosen_sector["icon"],
        "reward_type": r_type,
        "new_balance": user.credits_balance or 0,
        "is_free": is_free,
    }

    return True, f"🎉 Вы выиграли: {chosen_sector['title']}!", result_data


