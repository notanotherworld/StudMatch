"""
Тест проверки безопасности сброса свайпов:
- Гарантия сохранения Match (пар) и ChatMessage (сообщений) при сбросе свайпов в WebApp и боте
- Удаление исходящих свайпов по не-мэтчам (возвращение пропущенных анкет)
"""
import asyncio
import os
import sys
import json
import uuid
import sqlite3
from datetime import datetime, timezone

# Настраиваем UTF-8 для консоли Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_RESET_SAFETY")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_reset_safety.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete, or_, and_, case
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from database.models import (
    Base, User, Profile, ModeEnum, Swipe, SwipeAction, Match, ChatMessage
)
from database.crud import (
    get_user_matches, get_chat_messages
)
from web.routers.webapp import webapp_reset_swipes


async def run_test():
    db_path = "test_reset_safety.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        print("1. Создаем тестовых пользователей: User A (100), User B (200), User C (300)...")
        now = datetime.now(timezone.utc)
        user_a = User(id=100, tg_username="user_a", is_active=True, mode=ModeEnum.dating)
        user_b = User(id=200, tg_username="user_b", is_active=True, mode=ModeEnum.dating)
        user_c = User(id=300, tg_username="user_c", is_active=True, mode=ModeEnum.dating)
        db.add_all([user_a, user_b, user_c])
        await db.commit()

        prof_a = Profile(user_id=100, name="Алексей", is_visible=True, is_complete=True)
        prof_b = Profile(user_id=200, name="Алина", is_visible=True, is_complete=True)
        prof_c = Profile(user_id=300, name="Светлана", is_visible=True, is_complete=True)
        db.add_all([prof_a, prof_b, prof_c])
        await db.commit()

        print("2. Создаем взаимный мэтч между User A и User B, а также сообщения диалога...")
        match_id = uuid.uuid4()
        match_ab = Match(id=match_id, user1_id=100, user2_id=200, mode=ModeEnum.dating, created_at=now)
        swipe_a_to_b = Swipe(from_user_id=100, to_user_id=200, action=SwipeAction.like, mode=ModeEnum.dating, created_at=now)
        swipe_b_to_a = Swipe(from_user_id=200, to_user_id=100, action=SwipeAction.like, mode=ModeEnum.dating, created_at=now)
        
        # Свайп на User C (пропуск)
        swipe_a_to_c = Swipe(from_user_id=100, to_user_id=300, action=SwipeAction.skip, mode=ModeEnum.dating, created_at=now)

        db.add_all([match_ab, swipe_a_to_b, swipe_b_to_a, swipe_a_to_c])
        await db.commit()

        # Добавляем сообщения в чат между A и B
        msg1 = ChatMessage(id=uuid.uuid4(), match_id=match_id, sender_id=100, text="Привет, как дела?", is_read=True, created_at=now)
        msg2 = ChatMessage(id=uuid.uuid4(), match_id=match_id, sender_id=200, text="Привет! Всё отлично!", is_read=False, created_at=now)
        db.add_all([msg1, msg2])
        await db.commit()

        # Проверяем, что мэтч и сообщения на месте
        matches_before = await get_user_matches(db, 100)
        assert len(matches_before) == 1, "Должен быть 1 мэтч до сброса"
        msgs_before = await get_chat_messages(db, match_id)
        assert len(msgs_before) == 2, "Должно быть 2 сообщения до сброса"
        print(f"   -> До сброса: {len(matches_before)} мэтч, {len(msgs_before)} сообщений в чате.")

        print("3. Пользователь A нажимает «Начать сначала (сбросить свайпы)» в WebApp...")
        res = await webapp_reset_swipes(student=user_a, db=db)
        assert res["status"] == "ok", "Статус сброса должен быть ok"

        print("4. Проверяем состояние базы данных после сброса свайпов...")
        # 4.1 Мэтч должен сохраниться!
        match_in_db = await db.scalar(select(Match).where(Match.id == match_id))
        assert match_in_db is not None, "ОШИБКА: Match удалился! А должен был сохраниться!"

        # 4.2 Сообщения чата должны сохраниться!
        msgs_after = await get_chat_messages(db, match_id)
        assert len(msgs_after) == 2, f"ОШИБКА: Сообщения удалились! Ожидалось 2, получено {len(msgs_after)}"
        assert msgs_after[0].text == "Привет, как дела?"
        assert msgs_after[1].text == "Привет! Всё отлично!"

        # 4.3 get_user_matches для пользователя A и для пользователя B должны возвращать их пару!
        matches_a_after = await get_user_matches(db, 100)
        assert len(matches_a_after) == 1, "Мэтч пропал у пользователя A!"
        matches_b_after = await get_user_matches(db, 200)
        assert len(matches_b_after) == 1, "Мэтч пропал у собеседника (пользователя B)!"

        # 4.4 Исходящий свайп на User C (скип) должен быть успешно удален, чтобы анкета C вернулась в ленту!
        swipe_c_in_db = await db.scalar(select(Swipe).where(Swipe.from_user_id == 100, Swipe.to_user_id == 300))
        assert swipe_c_in_db is None, "Свайп на User C должен был удалиться для повторного показа в ленте!"

        # 4.5 Исходящий свайп на User B (лайк-мэтч) должен остаться, чтобы не ломать связку!
        swipe_b_in_db = await db.scalar(select(Swipe).where(Swipe.from_user_id == 100, Swipe.to_user_id == 200))
        assert swipe_b_in_db is not None, "Свайп на User B должен сохраниться для защиты мэтча!"

        print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО! Мэтчи и чаты сохранены, свайпы по не-мэтчам сброшены.")

    await engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_test())
