"""
Тесты комплексной системы стриков в стиле Duolingo для StudMatch:
1. Инкремент дневных свайпов (0 -> 1..4 -> 5).
2. Зажжение стрика на 5-м свайпе и начисление стипендии.
3. Повторные свайпы в тот же день не начисляют повторный бонус.
4. Продление серии на следующий день (день 2).
5. Защита серии заморозкой («Справка от врача» 🩺).
6. Сгорание серии и окно ремонта 48 часов («Отработка долга» за 25 🎓).
7. Истечение 48 часов на ремонт -> сброс серии в 0.
8. Покупка «Справки от врача» (лимит 2 шт., 15 🎓).
9. Вехи Клуба ударников (3, 7, 14, 30 дней) и разблокировка рамки frame_fire.
10. Генерация данных для Streak Hub (виджет, календарь, слоты защиты).
11. Выполнение дейлика автоматически зажигает стрик.
"""
import os
import sys
import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# UTF-8 вывод для Windows консоли
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_STREAK_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_streak.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import select, delete

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from database.session import engine, AsyncSessionLocal
from database.models import Base, User, Profile, EconomyTransaction, UserInventoryItem
from database.crud import (
    MSK_TZ,
    record_user_daily_activity,
    get_streak_hub_data,
    repair_broken_streak,
    buy_streak_freeze,
    claim_streak_milestone,
    process_daily_streak_expiration,
)
from bot.services.economy_service import get_frame_title


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if os.path.exists("test_streak.db"):
        try:
            os.remove("test_streak.db")
        except Exception:
            pass


@pytest.mark.asyncio
async def test_00_create_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_clean_user(user_id: int, initial_credits: int = 100) -> User:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EconomyTransaction).where(EconomyTransaction.user_id == user_id))
        await db.execute(delete(UserInventoryItem).where(UserInventoryItem.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()

        user = User(
            id=user_id,
            tg_username=f"user_{user_id}",
            credits_balance=initial_credits,
            streak_days=0,
            streak_freeze_count=0,
            today_swipes_count=0,
            streak_repair_available=False,
            streak_broken_at=None,
            streak_milestones_claimed=[],
        )
        db.add(user)
        await db.commit()
    return user


@pytest.mark.asyncio
async def test_streak_swipe_increment_and_ignite():
    """Проверка инкремента свайпов (1..5) и зажжения серии на 5-м свайпе."""
    uid = 9001
    await create_clean_user(uid, initial_credits=10)

    async with AsyncSessionLocal() as db:
        # Свайпы 1, 2, 3, 4
        for i in range(1, 5):
            res = await record_user_daily_activity(db, uid, action_type="swipe")
            assert res["today_swipes"] == i
            assert res["newly_ignited"] is False
            assert res["streak_days"] == 0

        # 5-й свайп -> зажжение!
        res5 = await record_user_daily_activity(db, uid, action_type="swipe")
        assert res5["today_swipes"] == 5
        assert res5["newly_ignited"] is True
        assert res5["streak_days"] == 1
        assert res5["reward_credits"] == 4  # День 1 стипендии по STREAK_REWARDS_MAP
        assert res5["already_ignited"] is True

        # 6-й свайп в тот же день -> не зажигает повторно
        res6 = await record_user_daily_activity(db, uid, action_type="swipe")
        assert res6["today_swipes"] == 6
        assert res6["newly_ignited"] is False
        assert res6["streak_days"] == 1
        assert res6["reward_credits"] == 0


@pytest.mark.asyncio
async def test_streak_next_day_continuation():
    """Проверка продления серии на следующий день."""
    uid = 9002
    await create_clean_user(uid, initial_credits=10)

    yesterday_utc = datetime.now(timezone.utc) - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        # Устанавливаем пользователю стрик за вчера
        res_u = await db.execute(select(User).where(User.id == uid))
        user = res_u.scalar_one()
        user.streak_days = 1
        user.last_streak_date = yesterday_utc
        user.last_activity_date = yesterday_utc
        user.today_swipes_count = 5
        await db.commit()

        # Сегодня: свайп 1 сбрасывает счётчик на 1
        s1 = await record_user_daily_activity(db, uid, action_type="swipe")
        assert s1["today_swipes"] == 1
        assert s1["newly_ignited"] is False

        # Добиваем до 5 свайпов
        for _ in range(3):
            await record_user_daily_activity(db, uid, action_type="swipe")
        s5 = await record_user_daily_activity(db, uid, action_type="swipe")

        assert s5["today_swipes"] == 5
        assert s5["newly_ignited"] is True
        assert s5["streak_days"] == 2
        assert s5["reward_credits"] == 6  # День 2 стипендии


@pytest.mark.asyncio
async def test_streak_freeze_protection():
    """Проверка авто-заморозки серии при пропуске 1 дня при наличии справки."""
    uid = 9003
    await create_clean_user(uid, initial_credits=10)

    # 2 дня назад был зажжён стрик (вчера пропущен), есть 1 справка
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    async with AsyncSessionLocal() as db:
        res_u = await db.execute(select(User).where(User.id == uid))
        user = res_u.scalar_one()
        user.streak_days = 5
        user.last_streak_date = two_days_ago
        user.last_activity_date = two_days_ago
        user.streak_freeze_count = 1
        await db.commit()

        # Пользователь делает 5 свайпов сегодня
        for _ in range(4):
            await record_user_daily_activity(db, uid, action_type="swipe")
        s5 = await record_user_daily_activity(db, uid, action_type="swipe")

        assert s5["newly_ignited"] is True
        assert s5["streak_days"] == 6  # Серия спасена и продлена!

        # Проверяем списание заморозки
        await db.refresh(user)
        assert user.streak_freeze_count == 0


@pytest.mark.asyncio
async def test_streak_broken_and_48h_repair():
    """Проверка сгорания серии при отсутствии справок и восстановления за 25 🎓."""
    uid = 9004
    await create_clean_user(uid, initial_credits=50)

    now_utc = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        res_u = await db.execute(select(User).where(User.id == uid))
        user = res_u.scalar_one()
        user.streak_days = 10
        user.streak_freeze_count = 0
        user.streak_broken_at = now_utc - timedelta(hours=12)
        user.streak_repair_available = True
        user.credits_balance = 50
        await db.commit()

        # Восстановление за 25 🎓
        success, msg, days = await repair_broken_streak(db, uid)
        assert success is True
        assert days == 10
        await db.refresh(user)
        assert user.streak_repair_available is False
        assert user.streak_broken_at is None
        assert user.credits_balance == 25


@pytest.mark.asyncio
async def test_streak_repair_expired_after_48h():
    """Проверка истечения 48-часового окна на восстановление серии."""
    uid = 9005
    await create_clean_user(uid, initial_credits=50)

    now_utc = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        res_u = await db.execute(select(User).where(User.id == uid))
        user = res_u.scalar_one()
        user.streak_days = 12
        user.streak_broken_at = now_utc - timedelta(hours=49)  # > 48 часов
        user.streak_repair_available = True
        await db.commit()

        success, msg, days = await repair_broken_streak(db, uid)
        assert success is False
        assert "истекло" in msg
        await db.refresh(user)
        assert user.streak_repair_available is False
        assert user.streak_days == 0


@pytest.mark.asyncio
async def test_buy_streak_freeze():
    """Проверка покупки «Справки от врача» (15 🎓, максимум 2)."""
    uid = 9006
    await create_clean_user(uid, initial_credits=50)

    async with AsyncSessionLocal() as db:
        # Покупка 1-й справки
        ok1, msg1, c1 = await buy_streak_freeze(db, uid)
        assert ok1 is True
        assert c1 == 1

        # Покупка 2-й справки
        ok2, msg2, c2 = await buy_streak_freeze(db, uid)
        assert ok2 is True
        assert c2 == 2

        # Попытка покупки 3-й справки (лимит 2)
        ok3, msg3, c3 = await buy_streak_freeze(db, uid)
        assert ok3 is False
        assert "максимальный" in msg3
        assert c3 == 2


@pytest.mark.asyncio
async def test_streak_milestones():
    """Проверка получения наград за вехи (3, 7, 14, 30 дней) и разблокировки frame_fire."""
    uid = 9007
    await create_clean_user(uid, initial_credits=0)

    async with AsyncSessionLocal() as db:
        res_u = await db.execute(select(User).where(User.id == uid))
        user = res_u.scalar_one()
        user.streak_days = 30
        user.superlike_balance = 0
        user.credits_balance = 0
        user.streak_freeze_count = 0
        await db.commit()

        # Веха 3 дня: +15 🎓
        ok3, msg3, d3 = await claim_streak_milestone(db, uid, 3)
        assert ok3 is True
        assert d3["credits"] == 15

        # Веха 7 дней: +1 суперлайк
        ok7, msg7, d7 = await claim_streak_milestone(db, uid, 7)
        assert ok7 is True
        assert d7["superlikes"] == 1

        # Веха 14 дней: +50 🎓 + 1 справка
        ok14, msg14, d14 = await claim_streak_milestone(db, uid, 14)
        assert ok14 is True
        assert d14["credits"] == 50
        assert d14["freeze"] == 1

        # Веха 30 дней: рамка frame_fire
        ok30, msg30, d30 = await claim_streak_milestone(db, uid, 30)
        assert ok30 is True
        assert d30["frame"] == "frame_fire"

        await db.refresh(user)
        assert user.equipped_frame == "frame_fire"
        assert get_frame_title("frame_fire") == "🔥 «Пламя стрика»"

        # Повторное получение той же вехи должно быть заблокировано
        ok_dup, msg_dup, _ = await claim_streak_milestone(db, uid, 30)
        assert ok_dup is False
        assert "уже получена" in msg_dup


@pytest.mark.asyncio
async def test_get_streak_hub_data():
    """Проверка генерации агрегированных данных для Streak Hub."""
    uid = 9008
    await create_clean_user(uid, initial_credits=30)

    async with AsyncSessionLocal() as db:
        res_u = await db.execute(select(User).where(User.id == uid))
        user = res_u.scalar_one()
        user.streak_days = 8
        user.streak_freeze_count = 1
        user.today_swipes_count = 5
        user.last_streak_date = datetime.now(timezone.utc)
        user.last_activity_date = datetime.now(timezone.utc)
        await db.commit()

        hub = await get_streak_hub_data(db, uid)
        assert hub["streak_days"] == 8
        assert hub["flame_state"] == "ignited"
        assert hub["is_ignited_today"] is True
        assert hub["is_streak_society"] is True
        assert hub["freeze_count"] == 1
        assert len(hub["week_calendar"]) == 7
        assert len(hub["milestones"]) == 4


@pytest.mark.asyncio
async def test_process_daily_streak_expiration():
    """Проверка полуночной обработки пропусков (списание справок и сгорание)."""
    uid_frozen = 9009
    uid_broken = 9010
    await create_clean_user(uid_frozen, initial_credits=10)
    await create_clean_user(uid_broken, initial_credits=10)

    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    async with AsyncSessionLocal() as db:
        # Пользователь 1: со справкой
        u1 = (await db.execute(select(User).where(User.id == uid_frozen))).scalar_one()
        u1.streak_days = 4
        u1.last_streak_date = two_days_ago
        u1.streak_freeze_count = 1

        # Пользователь 2: без справки
        u2 = (await db.execute(select(User).where(User.id == uid_broken))).scalar_one()
        u2.streak_days = 6
        u2.last_streak_date = two_days_ago
        u2.streak_freeze_count = 0

        await db.commit()

        res = await process_daily_streak_expiration(db)
        frozen_ids = [uid for uid, _ in res["frozen"]]
        broken_ids = [uid for uid, _ in res["broken"]]

        assert uid_frozen in frozen_ids
        assert uid_broken in broken_ids

        await db.refresh(u1)
        await db.refresh(u2)
        assert u1.streak_freeze_count == 0
        assert u1.streak_days == 4  # Сохранён!
        assert u2.streak_repair_available is True
        assert u2.streak_broken_at is not None
