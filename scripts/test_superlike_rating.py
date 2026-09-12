import os
import sys
import json
import sqlite3
import pytest

# UTF-8 вывод для Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('BOT_TOKEN', '123456:TEST_TOKEN_FOR_SUPERLIKE_RATING')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///test_superlike_rating.db')

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
from database.models import Base, User, Profile, SwipeAction, ModeEnum
from database.crud import create_swipe, get_profile


@pytest.mark.asyncio
async def test_superlike_increments_recipient_rating():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Создаем отправителя A (1) и получателя B (2)
        user_a = User(id=1, consent_given=True)
        user_b = User(id=2, consent_given=True)
        prof_b = Profile(user_id=2, name="Получатель", is_complete=True, is_visible=True, rating_score=10.0)

        db.add_all([user_a, user_b, prof_b])
        await db.commit()

        # 1. Обычный лайк — рейтинг не должен меняться
        await create_swipe(db, from_id=1, to_id=2, action=SwipeAction.like, mode=ModeEnum.dating)
        p_check = await get_profile(db, 2)
        assert p_check.rating_score == 10.0

        # 2. Суперлайк от A к B – рейтинг получателя должен вырасть на +1.0 (стать 11.0)
        await create_swipe(db, from_id=1, to_id=2, action=SwipeAction.superlike, mode=ModeEnum.dating)
        p_check2 = await get_profile(db, 2)
        assert p_check2.rating_score == 11.0

        # 3. Суперлайк от третьего пользователя C (3) к B — рейтинг должен стать 12.0
        user_c = User(id=3, consent_given=True)
        db.add(user_c)
        await db.commit()

        await create_swipe(db, from_id=3, to_id=2, action=SwipeAction.superlike, mode=ModeEnum.dating)
        p_check3 = await get_profile(db, 2)
        assert p_check3.rating_score == 12.0


@pytest.mark.asyncio
async def test_superlike_with_initial_zero_or_null_score():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user_x = User(id=10, consent_given=True)
        user_y = User(id=20, consent_given=True)
        prof_y = Profile(user_id=20, name="Новичок", is_complete=True, is_visible=True, rating_score=0.0)

        db.add_all([user_x, user_y, prof_y])
        await db.commit()

        # Отправляем суперлайк
        await create_swipe(db, from_id=10, to_id=20, action=SwipeAction.superlike, mode=ModeEnum.dating)

        prof_reloaded = await get_profile(db, 20)
        assert prof_reloaded.rating_score == 1.0


def test_ui_and_notification_texts():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    browse_path = os.path.join(base_dir, 'bot', 'handlers', 'browse.py')
    webapp_path = os.path.join(base_dir, 'web', 'templates', 'webapp.html')

    with open(browse_path, 'r', encoding='utf-8') as f:
        browse_code = f.read()

    assert "Тебе отправили суперлайк (+1 к рейтингу)!" in browse_code

    with open(webapp_path, 'r', encoding='utf-8') as f:
        html_code = f.read()

    assert "Полученный суперлайк" in html_code
    assert "+1 б." in html_code
