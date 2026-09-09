"""
Тестирование логики Зала Славы (Hall of Fame):
- GET /api/webapp/hall_of_fame?scope=all
- GET /api/webapp/hall_of_fame?scope=university
- Ранжирование по rating_score desc, email_verified desc
- Расчет позиции текущего пользователя (my_rank)
"""
import os
import sys
import asyncio
import json
import sqlite3
from datetime import datetime, timezone, timedelta

# UTF-8 вывод для Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_AUDIT_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_audit.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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

from database.session import engine, AsyncSessionLocal
from database.models import Base, User, Profile, University, ModeEnum
from web.routers.webapp import webapp_get_hall_of_fame


async def setup_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Университеты
        u1 = University(id=1, name="Российский университет дружбы народов", short_name="РУДН", email_domains="@rudn.ru", city="Москва")
        u2 = University(id=2, name="Московский государственный университет", short_name="МГУ", email_domains="@msu.ru", city="Москва")
        db.add_all([u1, u2])
        await db.commit()

        # 2. Пользователи и профили
        # Студент 1 (РУДН, 150 баллов, верифицирован)
        user1 = User(id=101, university_id=1, email_verified=True, is_active=True, created_at=datetime.now(timezone.utc) - timedelta(days=10))
        prof1 = Profile(user_id=101, name="Алиса", age=21, year=3, major="ИТ", is_complete=True, is_visible=True, rating_score=150.0)

        # Студент 2 (РУДН, 120 баллов, не верифицирован)
        user2 = User(id=102, university_id=1, email_verified=False, is_active=True, created_at=datetime.now(timezone.utc) - timedelta(days=9))
        prof2 = Profile(user_id=102, name="Борис", age=20, year=2, major="Экономика", is_complete=True, is_visible=True, rating_score=120.0)

        # Студент 3 (МГУ, 180 баллов, верифицирован)
        user3 = User(id=103, university_id=2, email_verified=True, is_active=True, created_at=datetime.now(timezone.utc) - timedelta(days=8))
        prof3 = Profile(user_id=103, name="Виктор", age=22, year=4, major="Мехмат", is_complete=True, is_visible=True, rating_score=180.0)

        # Студент 4 (РУДН, 50 баллов, верифицирован)
        user4 = User(id=104, university_id=1, email_verified=True, is_active=True, created_at=datetime.now(timezone.utc) - timedelta(days=7))
        prof4 = Profile(user_id=104, name="Дарья", age=19, year=1, major="Юрфак", is_complete=True, is_visible=True, rating_score=50.0)

        # Студент 5 (Невидимый профиль, не должен попасть)
        user5 = User(id=105, university_id=1, email_verified=True, is_active=True, created_at=datetime.now(timezone.utc) - timedelta(days=6))
        prof5 = Profile(user_id=105, name="Елена", age=20, year=2, major="Филология", is_complete=True, is_visible=False, rating_score=200.0)

        # Студент 6 (Без университета)
        user6 = User(id=106, university_id=None, email_verified=False, is_active=True, created_at=datetime.now(timezone.utc) - timedelta(days=5))
        prof6 = Profile(user_id=106, name="Жанна", age=23, year=5, major="Дизайн", is_complete=True, is_visible=True, rating_score=80.0)

        db.add_all([user1, prof1, user2, prof2, user3, prof3, user4, prof4, user5, prof5, user6, prof6])
        await db.commit()


async def run_hall_of_fame_tests():
    await setup_test_db()

    async with AsyncSessionLocal() as db:
        # Тест 1: scope="all" от лица Алисы (user1, РУДН)
        from database.crud import get_user
        alisa = await get_user(db, 101)
        
        res_all = await webapp_get_hall_of_fame(scope="all", student=alisa, db=db)
        assert res_all["status"] == "ok"
        assert res_all["scope"] == "all"
        assert res_all["has_university"] is True
        assert res_all["university_name"] == "РУДН"
        assert len(res_all["leaderboard"]) == 5, f"Ожидалось 5 видимых анкет, получено {len(res_all['leaderboard'])}"
        
        # Проверка порядка: 1st Виктор (180), 2nd Алиса (150), 3rd Борис (120), 4th Жанна (80), 5th Дарья (50)
        lb = res_all["leaderboard"]
        assert lb[0]["user_id"] == 103 and lb[0]["name"] == "Виктор" and lb[0]["rank"] == 1
        assert lb[1]["user_id"] == 101 and lb[1]["name"] == "Алиса" and lb[1]["rank"] == 2 and lb[1]["is_me"] is True
        assert lb[2]["user_id"] == 102 and lb[2]["name"] == "Борис" and lb[2]["rank"] == 3
        assert lb[3]["user_id"] == 106 and lb[3]["name"] == "Жанна" and lb[3]["rank"] == 4
        assert lb[4]["user_id"] == 104 and lb[4]["name"] == "Дарья" and lb[4]["rank"] == 5

        assert res_all["my_rank"] == 2
        assert res_all["my_score"] == 150.0
        print("  ✅ [1] Зал Славы (scope=all): корректная сортировка и расчет позиции 'is_me'")

        # Тест 2: scope="university" от лица Алисы (РУДН)
        res_univ = await webapp_get_hall_of_fame(scope="university", student=alisa, db=db)
        assert res_univ["status"] == "ok"
        assert res_univ["scope"] == "university"
        assert len(res_univ["leaderboard"]) == 3, f"В РУДН должно быть 3 студента, получено {len(res_univ['leaderboard'])}"
        
        # В РУДН: 1st Алиса (150), 2nd Борис (120), 3rd Дарья (50)
        lb_u = res_univ["leaderboard"]
        assert lb_u[0]["user_id"] == 101 and lb_u[0]["rank"] == 1 and lb_u[0]["is_me"] is True
        assert lb_u[1]["user_id"] == 102 and lb_u[1]["rank"] == 2
        assert lb_u[2]["user_id"] == 104 and lb_u[2]["rank"] == 3
        assert res_univ["my_rank"] == 1
        print("  ✅ [2] Зал Славы (scope=university): фильтрация по ВУЗу пользователя")

        # Тест 3: scope="university" от лица Виктора (МГУ)
        victor = await get_user(db, 103)
        res_vic = await webapp_get_hall_of_fame(scope="university", student=victor, db=db)
        assert len(res_vic["leaderboard"]) == 1
        assert res_vic["leaderboard"][0]["user_id"] == 103
        assert res_vic["my_rank"] == 1
        assert res_vic["university_name"] == "МГУ"
        print("  ✅ [3] Зал Славы (scope=university): корректный показ для другого ВУЗа (МГУ)")

        # Тест 4: scope="university" от лица Жанны (без ВУЗа)
        zhanna = await get_user(db, 106)
        res_zh = await webapp_get_hall_of_fame(scope="university", student=zhanna, db=db)
        assert res_zh["has_university"] is False
        assert res_zh["university_name"] is None
        assert res_zh["leaderboard"] == []
        assert res_zh["my_rank"] is None
        print("  ✅ [4] Зал Славы (scope=university): безопасная обработка пользователя без ВУЗа")


def test_hall_of_fame():
    asyncio.run(run_hall_of_fame_tests())


if __name__ == "__main__":
    print("=" * 60)
    print("🏆 ТЕСТИРОВАНИЕ ЗАЛА СЛАВЫ (HALL OF FAME API)")
    print("=" * 60)
    test_hall_of_fame()
    print("=" * 60)
    print("🎉 ВСЕ ТЕСТЫ ЗАЛА СЛАВЫ УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 60)
