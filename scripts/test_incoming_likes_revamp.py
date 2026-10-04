"""
Тестирование обновленного раздела «Симпатии» (Incoming Likes):
- Исключение пропущенных (skip) анкет из входящих
- Поддержка суперлайков с комментариями
- Разблокировка за 50 зачётов для пользователей без Премиума
- Бесплатный доступ для пользователей с Премиумом
- Фильтрация по режимам и корректность эндпоинтов
"""
import os
import sys
import json
import uuid
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_LIKES_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_likes_revamp.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import select, and_

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)
sqlite3.register_adapter(uuid.UUID, lambda u: str(u))
sqlite3.register_converter("UUID", lambda b: uuid.UUID(b.decode()))

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from database.session import engine, AsyncSessionLocal
from database.models import (
    Base, User, Profile, University, Swipe, SwipeAction, ModeEnum, EconomyTransaction
)
from database.crud import (
    create_swipe, get_incoming_likes, get_incoming_likes_count,
    get_unlocked_like_target_ids, spend_user_credits
)
from web.routers.webapp import webapp_incoming_likes, webapp_incoming_likes_unlock, UnlockLikeRequest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_incoming_likes_and_unlock_flow():
    # Инициализация БД
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Создаем университет
        uni = University(name="МГУ им. Ломоносова", short_name="МГУ", email_domains="@msu.ru", city="Москва")
        db.add(uni)
        await db.flush()

        # Создаем пользователей
        # User 1: Текущий студент (Freemium, 100 зачётов)
        user_me = User(
            id=1001,
            tg_username="student_me",
            is_active=True,
            premium_until=None,
            credits_balance=100,
            university_id=uni.id,
        )
        # User 2: Поставил обычный лайк в Dating
        user_like = User(
            id=2001,
            tg_username="anna_mgu",
            is_active=True,
            premium_until=None,
            university_id=uni.id,
        )
        # User 3: Поставил суперлайк с комментарием
        user_super = User(
            id=3001,
            tg_username="maria_hse",
            is_active=True,
            premium_until=datetime.now(timezone.utc) + timedelta(days=30),
            university_id=uni.id,
        )
        # User 4: Поставил лайк в Career
        user_career = User(
            id=4001,
            tg_username="alex_work",
            is_active=True,
            premium_until=None,
            university_id=uni.id,
        )

        db.add_all([user_me, user_like, user_super, user_career])
        await db.flush()

        # Создаем профили
        prof_me = Profile(user_id=user_me.id, name="Иван", age=20, year=2, is_visible=True)
        prof_like = Profile(user_id=user_like.id, name="Анна", age=19, year=1, is_visible=True, photos=["https://example.com/p1.jpg"])
        prof_super = Profile(user_id=user_super.id, name="Мария", age=21, year=3, is_visible=True, photos=["https://example.com/p2.jpg"])
        prof_career = Profile(user_id=user_career.id, name="Алексей", age=22, year=4, is_visible=True, photos=["https://example.com/p3.jpg"])
        db.add_all([prof_me, prof_like, prof_super, prof_career])
        await db.commit()

        # 1. Добавляем входящие свайпы:
        # Анна ставит лайк Ивану
        await create_swipe(db, from_id=user_like.id, to_id=user_me.id, action=SwipeAction.like, mode=ModeEnum.dating)
        # Мария ставит суперлайк с комментарием Ивану
        await create_swipe(db, from_id=user_super.id, to_id=user_me.id, action=SwipeAction.superlike, mode=ModeEnum.dating, comment="Привет, классная анкета!")
        # Алексей ставит лайк Ивану в режиме карьеры
        await create_swipe(db, from_id=user_career.id, to_id=user_me.id, action=SwipeAction.like, mode=ModeEnum.career)
        await db.commit()

        # 2. Проверяем get_incoming_likes и счетчики
        total_count = await get_incoming_likes_count(db, user_me.id)
        assert total_count == 3, f"Ожидалось 3 входящих лайка, получено {total_count}"

        dating_count = await get_incoming_likes_count(db, user_me.id, mode=ModeEnum.dating)
        assert dating_count == 2, f"Ожидалось 2 лайка в dating, получено {dating_count}"

        career_count = await get_incoming_likes_count(db, user_me.id, mode=ModeEnum.career)
        assert career_count == 1, f"Ожидалось 1 лайк в career, получено {career_count}"

        # 3. Вызываем API эндпоинт webapp_incoming_likes
        res = await webapp_incoming_likes(mode=None, student=user_me, db=db)
        assert res["status"] == "ok"
        assert res["count"] == 3
        assert res["superlikes_count"] == 1
        assert res["is_premium"] is False
        assert res["credits_balance"] == 100
        assert len(res["likes"]) == 3

        # Проверяем, что для пользователя без премиума карточки приходят с is_unlocked=False
        for item in res["likes"]:
            assert item["is_unlocked"] is False
            if item["user_id"] == user_super.id:
                assert item["is_superlike"] is True
                assert item["has_comment"] is True

        # 4. Разблокировка анкеты Анны за 50 зачётов
        unlock_req = UnlockLikeRequest(target_user_id=user_like.id)
        unlock_res = await webapp_incoming_likes_unlock(payload=unlock_req, student=user_me, db=db)
        assert unlock_res["status"] == "ok"
        assert unlock_res["is_unlocked"] is True
        assert unlock_res["credits_balance"] == 50, f"Баланс должен стать 50, получено {unlock_res['credits_balance']}"

        # 5. Повторный запрос webapp_incoming_likes - анкета Анны теперь is_unlocked=True
        res_after_unlock = await webapp_incoming_likes(mode=None, student=user_me, db=db)
        anna_card = next((x for x in res_after_unlock["likes"] if x["user_id"] == user_like.id), None)
        assert anna_card is not None
        assert anna_card["is_unlocked"] is True

        # Карточка Марии всё еще locked
        maria_card = next((x for x in res_after_unlock["likes"] if x["user_id"] == user_super.id), None)
        assert maria_card is not None
        assert maria_card["is_unlocked"] is False

        # 6. Проверка защиты: повторная разблокировка той же анкеты не списывает зачёты
        repeat_unlock = await webapp_incoming_likes_unlock(payload=unlock_req, student=user_me, db=db)
        assert repeat_unlock["credits_balance"] == 50

        # 7. Разблокировка Марии (50 зачётов) -> Баланс станет 0
        unlock_super = await webapp_incoming_likes_unlock(payload=UnlockLikeRequest(target_user_id=user_super.id), student=user_me, db=db)
        assert unlock_super["credits_balance"] == 0

        # 8. Попытка разблокировать Алексея при балансе 0 -> HTTPException 400
        with pytest.raises(HTTPException) as exc_info:
            await webapp_incoming_likes_unlock(payload=UnlockLikeRequest(target_user_id=user_career.id), student=user_me, db=db)
        assert exc_info.value.status_code == 400
        assert "Недостаточно зачётов" in exc_info.value.detail

        # 9. Проверка исключения после свайпа SKIP:
        # Иван пропускает Алексея (skip)
        await create_swipe(db, from_id=user_me.id, to_id=user_career.id, action=SwipeAction.skip, mode=ModeEnum.career)
        await db.commit()

        # Теперь Алексей должен исчезнуть из входящих лайков Ивана!
        count_after_skip = await get_incoming_likes_count(db, user_me.id)
        assert count_after_skip == 2, f"После skip ожидалось 2 входящих лайка, получено {count_after_skip}"

        likes_after_skip = await get_incoming_likes(db, user_me.id)
        remaining_ids = [lk.from_user_id for lk in likes_after_skip]
        assert user_career.id not in remaining_ids, "Пропущенный пользователь не должен появляться во входящих лайках!"

        # 10. Премиум пользователь видит все анкеты сразу с is_unlocked=True
        user_me.premium_until = datetime.now(timezone.utc) + timedelta(days=30)
        await db.commit()
        res_prem = await webapp_incoming_likes(mode=None, student=user_me, db=db)
        assert res_prem["is_premium"] is True
        for item in res_prem["likes"]:
            assert item["is_unlocked"] is True

    print("\n✅ Все тесты раздела «Симпатии» и разблокировки успешно пройдены!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_incoming_likes_and_unlock_flow())
