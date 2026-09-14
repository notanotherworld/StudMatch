"""
CRUD-операции для основных сущностей.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Collection, Set
import uuid
import random
import string
import logging
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, func, case, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from database.models import (
    User, Profile, University, EmailToken, Achievement,
    Swipe, Match, ChatMessage, Admin, Employer, EmployerProfileAccess, Payment, Report,
    VerifiedStatus, SwipeAction, ModeEnum, PaymentStatus, PaymentProduct, UserPrivacy,
    Project,
)


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
            gender_filters.append(or_(Profile.gender == "female", Profile.gender.is_(None)))
        elif viewer_profile.target_gender == "male":
            gender_filters.append(or_(Profile.gender == "male", Profile.gender.is_(None)))

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

    # Получаем последние 15 свайпов пользователя для скользящего буфера
    recent_swipes_res = await db.execute(
        select(Swipe.to_user_id)
        .where(
            Swipe.from_user_id == viewer_id,
            or_(Swipe.mode == current_mode, Swipe.mode.is_(None)),
        )
        .order_by(Swipe.created_at.desc())
        .limit(15)
    )
    recent_swiped_ids = list(recent_swipes_res.scalars().all())

    # Базовые условия выборки
    base_conditions = [
        Profile.is_visible == True,
        is_complete_cond,
        User.is_active == True,
        Profile.user_id != viewer_id,
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
            case((priority <= 1, viewer_swipe_time), else_=None).asc().nulls_last(),
            Profile.rating_score.desc(),
        )
        .limit(1)
    )

    # Проход 1: Со скользящим буфером (исключаем последние 10 свайпов, кроме активных входящих лайков)
    client_exclude: Set[int] = set(exclude_ids or ())
    recent_buffer: Set[int] = set(recent_swiped_ids[:10])

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


async def get_user_matches(db: AsyncSession, user_id: int) -> List[Tuple[Match, User]]:
    """Получить список всех мэтчей пользователя с деталями о партнере (с авто-восстановлением взаимных лайков)."""
    # 1. Автоматический бекфилл/исправление: находим все взаимные лайки, у которых нет записи в matches
    try:
        my_likes_res = await db.execute(
            select(Swipe.to_user_id).where(
                and_(
                    Swipe.from_user_id == user_id,
                    Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
                )
            )
        )
        my_liked_ids = [uid for uid in my_likes_res.scalars().all() if uid and uid != user_id]

        if my_liked_ids:
            mutual_res = await db.execute(
                select(Swipe.from_user_id).where(
                    and_(
                        Swipe.from_user_id.in_(my_liked_ids),
                        Swipe.to_user_id == user_id,
                        Swipe.action.in_([SwipeAction.like, SwipeAction.superlike]),
                    )
                )
            )
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

                    exist_match = await db.scalar(
                        select(Match).where(
                            or_(
                                and_(Match.user1_id == user_id, Match.user2_id == partner_id),
                                and_(Match.user1_id == partner_id, Match.user2_id == user_id),
                            )
                        )
                    )
                    if not exist_match:
                        db.add(Match(id=uuid.uuid4(), user1_id=user_id, user2_id=partner_id, mode=ModeEnum.dating))
                await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Failed to auto-heal matches for user {user_id}: {e}")

    # 2. Выбираем все актуальные мэтчи с пакетной загрузкой партнеров (устранение N+1)
    try:
        query = (
            select(Match)
            .where(or_(Match.user1_id == user_id, Match.user2_id == user_id))
            .order_by(Match.created_at.desc())
        )
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
        added_partners = set()
        for m in matches:
            partner_id = m.user2_id if m.user1_id == user_id else m.user1_id
            if partner_id in added_partners or partner_id == user_id:
                continue
            partner = partners_map.get(partner_id)
            if partner and getattr(partner, "is_active", True):
                added_partners.add(partner_id)
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
    query = select(Match).where(
        or_(
            and_(Match.user1_id == user1_id, Match.user2_id == user2_id),
            and_(Match.user1_id == user2_id, Match.user2_id == user1_id),
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
) -> List[Project]:
    swiped_stmt = select(Swipe.to_project_id).where(
        and_(
            Swipe.from_user_id == viewer_user_id,
            Swipe.to_project_id.isnot(None),
        )
    )
    swiped_res = await db.execute(swiped_stmt)
    swiped_project_ids = set(swiped_res.scalars().all())

    stmt = (
        select(Project)
        .options(
            selectinload(Project.user).selectinload(User.profile),
            selectinload(Project.user).selectinload(User.university),
        )
        .where(
            and_(
                Project.is_active.is_(True),
                Project.user_id != viewer_user_id,
            )
        )
    )

    if swiped_project_ids:
        stmt = stmt.where(Project.id.not_in(swiped_project_ids))

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
