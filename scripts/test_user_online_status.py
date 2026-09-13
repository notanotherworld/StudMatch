"""
Тесты проверки честного статуса онлайн и времени активности пользователей (StudMatch).
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone, timedelta
import pytest

# UTF-8 вывод для Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('BOT_TOKEN', '123456:TEST_TOKEN_FOR_ONLINE_STATUS')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///test_online_status.db')

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
from database.models import Base, User, Profile, Match, ModeEnum
from database.crud import update_user_last_active, get_user


def test_user_is_online_property():
    now = datetime.now(timezone.utc)
    
    # 1. Активен 2 минуты назад -> онлайн
    user_recent = User(id=1, is_fake=False, last_active_at=now - timedelta(minutes=2))
    assert user_recent.is_online is True
    assert user_recent.online_status_text == "онлайн"

    # 2. Активен 6 минут назад -> оффлайн, был недавно
    user_past_5m = User(id=2, is_fake=False, last_active_at=now - timedelta(minutes=6))
    assert user_past_5m.is_online is False
    assert user_past_5m.online_status_text == "был(а) недавно"

    # 3. Активен 2 дня назад -> был давно
    user_old = User(id=3, is_fake=False, last_active_at=now - timedelta(days=2))
    assert user_old.is_online is False
    assert user_old.online_status_text == "был(а) давно"

    # 4. Никогда не был активен -> был давно
    user_none = User(id=4, is_fake=False, last_active_at=None)
    assert user_none.is_online is False
    assert user_none.online_status_text == "был(а) давно"

    # 5. Фейковый / тестовый профиль -> всегда оффлайн
    user_fake = User(id=5, is_fake=True, last_active_at=now - timedelta(seconds=10))
    assert user_fake.is_online is False
    assert user_fake.online_status_text == "был(а) давно"


@pytest.mark.asyncio
async def test_update_user_last_active_in_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user = User(id=777, consent_given=True, last_active_at=None)
        db.add(user)
        await db.commit()

        # Обновляем активность
        await update_user_last_active(db, 777, force=True)

        user_reloaded = await get_user(db, 777)
        assert user_reloaded.last_active_at is not None
        assert user_reloaded.is_online is True


@pytest.mark.asyncio
async def test_webapp_matches_and_messages_online_fields():
    from web.routers.webapp import webapp_matches, webapp_get_match_messages
    now = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        student = User(id=801, consent_given=True, last_active_at=now)
        student_p = Profile(user_id=801, name="Я", is_complete=True)

        partner = User(id=802, consent_given=True, last_active_at=now - timedelta(minutes=1))
        partner_p = Profile(user_id=802, name="Партнер", is_complete=True)

        match = Match(user1_id=801, user2_id=802, mode=ModeEnum.dating)

        db.add_all([student, student_p, partner, partner_p, match])
        await db.commit()

        # Проверка webapp_matches
        matches_res = await webapp_matches(student=student, db=db)
        assert matches_res["status"] == "ok"
        assert len(matches_res["matches"]) == 1
        m_item = matches_res["matches"][0]
        assert m_item["is_online"] is True
        assert m_item["online_status_text"] == "онлайн"

        # Проверка webapp_get_match_messages
        chat_res = await webapp_get_match_messages(match_id=str(match.id), student=student, db=db)
        assert chat_res["status"] == "ok"
        assert chat_res["partner"]["is_online"] is True
        assert chat_res["partner"]["online_status_text"] == "онлайн"


def test_ui_and_css_online_dot_presence():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    js_path = os.path.join(base_dir, 'web', 'static', 'webapp', 'webapp.js')
    css_path = os.path.join(base_dir, 'web', 'static', 'webapp', 'webapp.css')

    with open(js_path, 'r', encoding='utf-8') as f:
        js_code = f.read()

    with open(css_path, 'r', encoding='utf-8') as f:
        css_code = f.read()

    # Проверка наличия match-online-dot в CSS и JS
    assert ".match-online-dot" in css_code
    assert "match-online-dot" in js_code

    # Проверка устранения захардкоженного "онлайн"
    assert "chatPartnerStatus.textContent = currentChatPartner.online_status_text" in js_code
