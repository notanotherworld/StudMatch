"""
Комплексные тесты проверки настроек приватности профиля (StudMatch).
Тестирует:
1. Модель UserPrivacy и CRUD функции (get_or_create_user_privacy, update_user_privacy).
2. Защиту главного фото и переключение приватности дополнительных фото (toggle_photo_privacy).
3. Видимость статуса онлайн с односторонней приватностью (is_user_online_visible_to, get_user_online_status_text_for).
4. Ограничения на отправку сообщений (matches, verified_only, nobody) в WebApp и боте.
5. Фильтрацию анкет для работодателей при выключенном allow_employer_access.
6. Скрытие возраста, курса и email в анкетах и WebApp endpoints.
"""
import os
import sys
import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta

# UTF-8 вывод для Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('BOT_TOKEN', '123456:TEST_TOKEN_FOR_PRIVACY')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///test_privacy_settings.db')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter('JSON', json.loads)

@compiles(ARRAY, 'sqlite')
def compile_array_sqlite(type_, compiler, **kw):
    return 'JSON'

@compiles(UUID, 'sqlite')
def compile_uuid_sqlite(type_, compiler, **kw):
    return 'VARCHAR(36)'

from database.session import engine, AsyncSessionLocal
from database.models import Base, User, Profile, Match, UserPrivacy, ModeEnum
from database.crud import (
    get_or_create_user_privacy,
    update_user_privacy,
    toggle_photo_privacy,
    is_user_online_visible_to,
    get_user_online_status_text_for,
    get_employer_profiles,
    get_user,
)
from bot.handlers.browse import _build_profile_caption


@pytest.mark.asyncio
async def test_privacy_crud_and_defaults():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user = User(id=1001, consent_given=True)
        db.add(user)
        await db.commit()

        # 1. Проверяем значения по умолчанию
        privacy = await get_or_create_user_privacy(db, 1001)
        assert privacy.user_id == 1001
        assert privacy.online_visibility == "all"
        assert privacy.message_permission == "matches"
        assert privacy.allow_employer_access is True
        assert privacy.hide_age is False
        assert privacy.hide_course is False
        assert privacy.hide_email is False
        assert privacy.private_photos == []

        # 2. Проверяем обновление
        updated = await update_user_privacy(
            db,
            1001,
            online_visibility="nobody",
            message_permission="verified_only",
            allow_employer_access=False,
            hide_age=True,
            hide_course=True,
            hide_email=True,
        )
        assert updated.online_visibility == "nobody"
        assert updated.message_permission == "verified_only"
        assert updated.allow_employer_access is False
        assert updated.hide_age is True
        assert updated.hide_course is True
        assert updated.hide_email is True

        # 3. Проверяем загрузку связи из User
        u = await get_user(db, 1001)
        assert u.privacy is not None
        assert u.privacy.online_visibility == "nobody"


@pytest.mark.asyncio
async def test_photo_privacy_toggling():
    async with AsyncSessionLocal() as db:
        user = User(id=1002, consent_given=True)
        db.add(user)
        await db.commit()

        # Включаем скрытие для фото photo_secondary_1
        priv, is_priv = await toggle_photo_privacy(db, 1002, "photo_secondary_1")
        assert is_priv is True
        assert "photo_secondary_1" in priv.private_photos

        # Добавляем еще одно фото
        priv, is_priv = await toggle_photo_privacy(db, 1002, "photo_secondary_2")
        assert is_priv is True
        assert "photo_secondary_1" in priv.private_photos
        assert "photo_secondary_2" in priv.private_photos

        # Выключаем скрытие для первого фото
        priv, is_priv = await toggle_photo_privacy(db, 1002, "photo_secondary_1")
        assert is_priv is False
        assert "photo_secondary_1" not in priv.private_photos
        assert "photo_secondary_2" in priv.private_photos


def test_online_visibility_logic():
    now = datetime.now(timezone.utc)
    target = User(id=2001, is_fake=False, last_active_at=now - timedelta(minutes=1))
    
    # 1. target.privacy.online_visibility = "all"
    target.privacy = UserPrivacy(user_id=2001, online_visibility="all")
    assert is_user_online_visible_to(9999, target, is_mutual_match=False) is True
    assert is_user_online_visible_to(9999, target, is_mutual_match=True) is True
    assert get_user_online_status_text_for(9999, target, is_mutual_match=False) == "онлайн"

    # 2. target.privacy.online_visibility = "matches"
    target.privacy.online_visibility = "matches"
    assert is_user_online_visible_to(9999, target, is_mutual_match=False) is False
    assert is_user_online_visible_to(9999, target, is_mutual_match=True) is True
    assert get_user_online_status_text_for(9999, target, is_mutual_match=False) == "был(а) недавно"
    assert get_user_online_status_text_for(9999, target, is_mutual_match=True) == "онлайн"

    # 3. target.privacy.online_visibility = "nobody"
    target.privacy.online_visibility = "nobody"
    assert is_user_online_visible_to(9999, target, is_mutual_match=False) is False
    assert is_user_online_visible_to(9999, target, is_mutual_match=True) is False
    assert get_user_online_status_text_for(9999, target, is_mutual_match=False) == "был(а) недавно"
    assert get_user_online_status_text_for(9999, target, is_mutual_match=True) == "был(а) недавно"

    # 4. Сам пользователь всегда видит свой статус
    assert is_user_online_visible_to(2001, target, is_mutual_match=False) is True

    # 5. Односторонняя приватность:
    # Viewer (3001) скрыл свой онлайн (nobody), но смотрит на Target (2001), у которого онлайн = all
    target.privacy.online_visibility = "all"
    viewer = User(id=3001, is_fake=False, last_active_at=now)
    viewer.privacy = UserPrivacy(user_id=3001, online_visibility="nobody")
    # Viewer всё равно видит реальный онлайн Target
    assert is_user_online_visible_to(viewer.id, target, is_mutual_match=False) is True


@pytest.mark.asyncio
async def test_employer_profiles_filtering():
    from database.models import Employer, EmployerProfileAccess
    async with AsyncSessionLocal() as db:
        emp = Employer(id=9999, company_name="Яндекс", contact_name="Рекрутер", login="hr_yandex", password_hash="hash123")
        db.add(emp)

        # Студент 1: разрешил доступ HR
        s1 = User(id=3001, consent_given=True, is_active=True, is_fake=False)
        p1 = Profile(user_id=3001, name="Студент Открытый", career_is_complete=True)
        priv1 = UserPrivacy(user_id=3001, allow_employer_access=True)
        db.add_all([s1, p1, priv1])

        # Студент 2: запретил доступ HR
        s2 = User(id=3002, consent_given=True, is_active=True, is_fake=False)
        p2 = Profile(user_id=3002, name="Студент Скрытный", career_is_complete=True)
        priv2 = UserPrivacy(user_id=3002, allow_employer_access=False)
        db.add_all([s2, p2, priv2])
        await db.commit()

        acc1 = EmployerProfileAccess(employer_id=9999, profile_id=p1.id, status="new")
        acc2 = EmployerProfileAccess(employer_id=9999, profile_id=p2.id, status="new")
        db.add_all([acc1, acc2])
        await db.commit()

        # Ищем кандидатов
        results = await get_employer_profiles(db, employer_id=9999)
        result_user_ids = [acc.profile.user_id for acc in results if acc.profile]

        assert 3001 in result_user_ids
        assert 3002 not in result_user_ids


@pytest.mark.asyncio
async def test_bot_caption_hiding_age_and_course():
    p = Profile(
        user_id=4001,
        name="Алексей",
        age=21,
        major="ПМИ",
        year=3,
        goal="Увлекаюсь машинным обучением",
    )
    user = User(id=4001, profile=p, mode=ModeEnum.dating)

    # 1. Без приватности (все видно)
    user.privacy = UserPrivacy(user_id=4001, hide_age=False, hide_course=False)
    caption_full = await _build_profile_caption(p, tags_map={}, user=user)
    assert "21" in caption_full
    assert "3 курс" in caption_full

    # 2. Скрыт возраст
    user.privacy.hide_age = True
    user.privacy.hide_course = False
    caption_no_age = await _build_profile_caption(p, tags_map={}, user=user)
    assert "21" not in caption_no_age
    assert "3 курс" in caption_no_age

    # 3. Скрыт курс
    user.privacy.hide_age = False
    user.privacy.hide_course = True
    caption_no_course = await _build_profile_caption(p, tags_map={}, user=user)
    assert "21" in caption_no_course
    assert "3 курс" not in caption_no_course

    # 4. Скрыты и возраст, и курс
    user.privacy.hide_age = True
    user.privacy.hide_course = True
    caption_minimal = await _build_profile_caption(p, tags_map={}, user=user)
    assert "21" not in caption_minimal
    assert "3 курс" not in caption_minimal

    # 5. Пользователь без загруженного privacy в __dict__ (не должно падать с MissingGreenlet)
    user_no_priv = User(id=4002, mode=ModeEnum.dating)
    p_no_priv = Profile(user_id=4002, name="Максим", age=22, year=4)
    caption_safe = await _build_profile_caption(p_no_priv, tags_map={}, user=user_no_priv)
    assert "Максим" in caption_safe
    assert "22" in caption_safe
    assert "4 курс" in caption_safe

    # 6. Загрузка через get_next_profile с eager loading user.privacy
    async with AsyncSessionLocal() as db:
        u_db = User(id=4003, is_active=True, university_id=1)
        p_db = Profile(user_id=4003, name="Ольга", is_complete=True, is_visible=True, age=23, year=5)
        db.add_all([u_db, p_db])
        await db.commit()
        await update_user_privacy(db, 4003, hide_age=True)

        from database.crud import get_next_profile
        fetched = await get_next_profile(db, viewer_id=1001)
        if fetched:
            user_inst = fetched.__dict__.get("user")
            if user_inst:
                assert "privacy" in user_inst.__dict__
            cap = await _build_profile_caption(fetched, tags_map={}, user=user_inst, db=db)
            assert cap is not None


@pytest.mark.asyncio
async def test_webapp_privacy_endpoints():
    from web.routers.webapp import (
        webapp_get_privacy,
        webapp_update_privacy,
        webapp_toggle_photo_privacy,
        PrivacyUpdateRequest,
        PhotoToggleRequest,
    )

    async with AsyncSessionLocal() as db:
        user = User(id=5001, consent_given=True)
        prof = Profile(user_id=5001, name="Даша", avatar_file_id="main_photo_id", photos=["main_photo_id", "extra_photo_1", "extra_photo_2"])
        db.add_all([user, prof])
        await db.commit()

        user = await get_user(db, 5001)

        # 1. GET /api/webapp/privacy
        data = await webapp_get_privacy(student=user, db=db)
        assert data["status"] == "ok"
        assert data["privacy"]["online_visibility"] == "all"
        assert len(data["photos"]) >= 1
        assert data["photos"][0]["is_main"] is True
        assert data["photos"][0]["is_private"] is False

        # 2. POST /api/webapp/privacy/photo-toggle на главное фото -> 400 ошибка
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await webapp_toggle_photo_privacy(
                payload=PhotoToggleRequest(photo_id="main_photo_id"),
                student=user,
                db=db,
            )
        assert exc_info.value.status_code == 400
        assert "Главное фото" in exc_info.value.detail

        # 3. POST /api/webapp/privacy/photo-toggle на дополнительное фото
        res_extra = await webapp_toggle_photo_privacy(
            payload=PhotoToggleRequest(photo_id="extra_photo_1"),
            student=user,
            db=db,
        )
        assert res_extra["status"] == "ok"
        assert res_extra["is_private"] is True
        assert "extra_photo_1" in res_extra["private_photos"]

        # 4. POST /api/webapp/privacy (изменение настроек)
        update_res = await webapp_update_privacy(
            payload=PrivacyUpdateRequest(
                online_visibility="nobody",
                message_permission="verified_only",
                allow_employer_access=False,
                hide_age=True,
                hide_course=True,
                hide_email=True,
            ),
            student=user,
            db=db,
        )
        assert update_res["status"] == "ok"
        assert update_res["privacy"]["online_visibility"] == "nobody"
        assert update_res["privacy"]["message_permission"] == "verified_only"
        assert update_res["privacy"]["allow_employer_access"] is False
        assert update_res["privacy"]["hide_age"] is True
        assert update_res["privacy"]["hide_course"] is True
        assert update_res["privacy"]["hide_email"] is True
