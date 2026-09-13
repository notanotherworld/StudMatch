"""
Unit-тесты для эндпоинтов загрузки и удаления фотографий в галерее профиля студента (StudMatch).
Тестирует:
1. Загрузка фото в галерею (POST /api/webapp/profile/photos) с ограничением до 6 фото.
2. Проверка обновления avatar_file_id при первой загрузке.
3. Удаление фото по индексу и по photo_url (DELETE /api/webapp/profile/photos).
4. Удаление последней фотографии — корректный сброс в avatar_file_id = None и photos = [].
5. Ошибки при превышении лимита (6 фото) или удалении несуществующего фото.
"""
import os
import sys
import io
import json
import sqlite3
import pytest
from unittest.mock import patch
from fastapi import UploadFile, HTTPException

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('BOT_TOKEN', '123456:TEST_TOKEN_FOR_GALLERY')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///test_gallery.db')

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
from database.models import Base, User, Profile
from web.routers.webapp import (
    webapp_upload_profile_photo,
    webapp_delete_profile_photo,
    PhotoDeleteRequest,
)


@pytest.mark.asyncio
async def test_gallery_upload_and_limit():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        user = User(
            id=777001,
            tg_username="phototester",
            is_active=True,
            consent_given=True,
        )
        profile = Profile(
            user_id=777001,
            name="Photo Tester",
            photos=[],
            avatar_file_id=None,
        )
        session.add(user)
        session.add(profile)
        await session.commit()
        user.profile = profile

        with patch("web.utils.uploads.save_avatar_upload") as mock_save:
            # 1. Загрузка первой фотографии
            mock_save.return_value = "/static/uploads/avatars/photo_1.jpg"
            dummy_file = UploadFile(filename="photo1.jpg", file=io.BytesIO(b"fake-image-bytes-1"))
            res1 = await webapp_upload_profile_photo(photo=dummy_file, student=user, db=session)

            assert res1["status"] == "ok"
            assert len(res1["photos"]) == 1
            assert "/static/uploads/avatars/photo_1.jpg" in res1["photo_url"]
            assert profile.avatar_file_id == "/static/uploads/avatars/photo_1.jpg"

            # 2. Загрузка еще 4 фото (всего 5)
            for i in range(2, 6):
                mock_save.return_value = f"/static/uploads/avatars/photo_{i}.jpg"
                f = UploadFile(filename=f"photo{i}.jpg", file=io.BytesIO(b"img"))
                await webapp_upload_profile_photo(photo=f, student=user, db=session)

            assert len(profile.photos) == 5

            # 3. Загрузка 6-го фото (максимум)
            mock_save.return_value = "/static/uploads/avatars/photo_6.jpg"
            f6 = UploadFile(filename="photo6.jpg", file=io.BytesIO(b"img6"))
            res6 = await webapp_upload_profile_photo(photo=f6, student=user, db=session)
            assert len(profile.photos) == 6

            # 4. Попытка загрузить 7-е фото (превышение лимита -> 400)
            mock_save.return_value = "/static/uploads/avatars/photo_7.jpg"
            f7 = UploadFile(filename="photo7.jpg", file=io.BytesIO(b"img7"))
            with pytest.raises(HTTPException) as exc:
                await webapp_upload_profile_photo(photo=f7, student=user, db=session)
            assert exc.value.status_code == 400
            assert "максимум 6" in exc.value.detail


@pytest.mark.asyncio
async def test_gallery_delete_by_index_and_url():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        user = User(
            id=777002,
            tg_username="deleter_user",
            is_active=True,
            consent_given=True,
        )
        profile = Profile(
            user_id=777002,
            name="Deleter",
            photos=[
                "/static/uploads/avatars/del_1.jpg",
                "/static/uploads/avatars/del_2.jpg",
                "/static/uploads/avatars/del_3.jpg",
            ],
            avatar_file_id="/static/uploads/avatars/del_1.jpg",
        )
        session.add(user)
        session.add(profile)
        await session.commit()
        user.profile = profile

        # 1. Удаление по индексу (удаляем index 1 -> del_2.jpg)
        req = PhotoDeleteRequest(index=1)
        res = await webapp_delete_profile_photo(payload=req, student=user, db=session)
        assert res["status"] == "ok"
        assert len(profile.photos) == 2
        assert "/static/uploads/avatars/del_2.jpg" not in profile.photos

        # 2. Удаление по URL (удаляем del_1.jpg, которое было avatar_file_id)
        req2 = PhotoDeleteRequest(photo_url="/static/uploads/avatars/del_1.jpg")
        res2 = await webapp_delete_profile_photo(payload=req2, student=user, db=session)
        assert res2["status"] == "ok"
        assert len(profile.photos) == 1
        assert profile.photos[0] == "/static/uploads/avatars/del_3.jpg"
        assert profile.avatar_file_id == "/static/uploads/avatars/del_3.jpg"

        # 3. Удаление последнего оставшегося фото
        req3 = PhotoDeleteRequest(index=0)
        res3 = await webapp_delete_profile_photo(payload=req3, student=user, db=session)
        assert res3["status"] == "ok"
        assert len(profile.photos) == 0
        assert profile.avatar_file_id is None

        # 4. Попытка удаления из пустого списка -> 404
        req4 = PhotoDeleteRequest(index=0)
        with pytest.raises(HTTPException) as exc:
            await webapp_delete_profile_photo(payload=req4, student=user, db=session)
        assert exc.value.status_code == 404
