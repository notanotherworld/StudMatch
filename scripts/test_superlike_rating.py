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


@pytest.mark.asyncio
async def test_transfer_superlike_rating_crud():
    from database.crud import transfer_superlike_rating, get_user

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Отправитель с 2 суперлайками
        sender = User(id=100, consent_given=True, superlike_balance=2)
        sender_prof = Profile(user_id=100, name="Даритель", is_complete=True, is_visible=True, rating_score=1.0)
        # Получатель
        target = User(id=200, consent_given=True, superlike_balance=0)
        target_prof = Profile(user_id=200, name="Адресат", is_complete=True, is_visible=True, rating_score=5.0)

        db.add_all([sender, sender_prof, target, target_prof])
        await db.commit()

        # 1. Первая отправка: 2 -> 1 суперлайк, рейтинг 5.0 -> 6.0
        res1 = await transfer_superlike_rating(db, 100, 200)
        assert res1["success"] is True
        assert res1["new_target_rating"] == 6.0
        assert res1["remaining_superlikes"] == 1
        assert res1["sender_name"] == "Даритель"
        assert res1["target_name"] == "Адресат"

        # 2. Вторая отправка: 1 -> 0 суперлайков, рейтинг 6.0 -> 7.0
        res2 = await transfer_superlike_rating(db, 100, 200)
        assert res2["success"] is True
        assert res2["new_target_rating"] == 7.0
        assert res2["remaining_superlikes"] == 0

        # 3. Третья отправка: баланс 0 -> отказ
        res3 = await transfer_superlike_rating(db, 100, 200)
        assert res3["success"] is False
        assert res3["error"] == "insufficient_balance"
        assert res3["remaining_superlikes"] == 0

        # 4. Попытка отправить себе: запрещено
        res_self = await transfer_superlike_rating(db, 100, 100)
        assert res_self["success"] is False
        assert res_self["error"] == "self_transfer_forbidden"

        # 5. Попытка отправить несуществующему пользователю
        res_missing = await transfer_superlike_rating(db, 100, 99999)
        assert res_missing["success"] is False
        assert res_missing["error"] == "target_not_found"


def test_webapp_and_bot_integration_code():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    browse_path = os.path.join(base_dir, 'bot', 'handlers', 'browse.py')
    webapp_js_path = os.path.join(base_dir, 'web', 'static', 'webapp', 'webapp.js')
    webapp_css_path = os.path.join(base_dir, 'web', 'static', 'webapp', 'webapp.css')
    webapp_router_path = os.path.join(base_dir, 'web', 'routers', 'webapp.py')

    with open(browse_path, 'r', encoding='utf-8') as f:
        browse_code = f.read()
    assert "gift:rating:" in browse_code
    assert "handle_gift_rating" in browse_code
    assert "Подарить +1 к рейтингу" in browse_code

    with open(webapp_js_path, 'r', encoding='utf-8') as f:
        js_code = f.read()
    assert "handleSendRatingToUser" in js_code
    assert "sheetSendRatingBtn" in js_code
    assert "matchSendRatingBtn" in js_code
    assert "sheetRatingBadge" in js_code
    assert "matchRatingBadge" in js_code
    assert "/api/webapp/profile/send_rating" in js_code

    with open(webapp_css_path, 'r', encoding='utf-8') as f:
        css_code = f.read()
    assert ".sheet-rating-badge" in css_code
    assert ".btn-send-rating" in css_code

    with open(webapp_router_path, 'r', encoding='utf-8') as f:
        router_code = f.read()
    assert "/api/webapp/profile/send_rating" in router_code
    assert "webapp_send_rating" in router_code
    assert "SendRatingRequest" in router_code


@pytest.mark.asyncio
async def test_api_webapp_send_rating_endpoint():
    from web.routers.webapp import webapp_send_rating, SendRatingRequest
    from fastapi import HTTPException
    from unittest.mock import AsyncMock, patch

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user_sender = User(id=301, consent_given=True, superlike_balance=1)
        prof_sender = Profile(user_id=301, name="Алиса", is_complete=True, is_visible=True, rating_score=2.0)
        user_target = User(id=302, consent_given=True, superlike_balance=0)
        prof_target = Profile(user_id=302, name="Боб", is_complete=True, is_visible=True, rating_score=8.0)

        db.add_all([user_sender, prof_sender, user_target, prof_target])
        await db.commit()

        # Mock Bot.send_message
        with patch("aiogram.Bot.send_message", new_callable=AsyncMock) as mock_send, \
             patch("aiogram.client.session.aiohttp.AiohttpSession.close", new_callable=AsyncMock):
            req = SendRatingRequest(target_user_id=302)
            resp = await webapp_send_rating(req, student=user_sender, db=db)
            assert resp["status"] == "ok"
            assert resp["new_target_rating"] == 9.0
            assert resp["remaining_superlikes"] == 0
            assert resp["target_name"] == "Боб"
            assert mock_send.called

        # Повторный запрос — баланс 0 -> HTTPException 400
        with pytest.raises(HTTPException) as exc_info:
            req = SendRatingRequest(target_user_id=302)
            await webapp_send_rating(req, student=user_sender, db=db)
        assert exc_info.value.status_code == 400
        assert "Недостаточно суперлайков" in exc_info.value.detail

        # Запрос самому себе -> HTTPException 400
        with pytest.raises(HTTPException) as exc_self:
            req = SendRatingRequest(target_user_id=301)
            await webapp_send_rating(req, student=user_sender, db=db)
        assert exc_self.value.status_code == 400
        assert "Нельзя отправить рейтинг самому себе" in exc_self.value.detail


@pytest.mark.asyncio
async def test_bot_gift_rating_callback():
    from bot.handlers.browse import handle_gift_rating
    from unittest.mock import AsyncMock, MagicMock, patch

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user_donor = User(id=401, consent_given=True, superlike_balance=1)
        prof_donor = Profile(user_id=401, name="Даритель Бот", is_complete=True, is_visible=True, rating_score=3.0)
        user_recip = User(id=402, consent_given=True, superlike_balance=0)
        prof_recip = Profile(user_id=402, name="Получатель Бот", is_complete=True, is_visible=True, rating_score=4.0)

        db.add_all([user_donor, prof_donor, user_recip, prof_recip])
        await db.commit()

        # Создаем мок callback query
        mock_cb = MagicMock()
        mock_cb.data = "gift:rating:402"
        mock_cb.answer = AsyncMock()
        mock_cb.bot = MagicMock()
        mock_cb.bot.send_message = AsyncMock()
        mock_cb.message = MagicMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.message.edit_reply_markup = AsyncMock()

        # Вызываем хэндлер бота
        await handle_gift_rating(mock_cb, user=user_donor, db=db)

        # Проверяем, что ответ отправлен дарителю
        assert mock_cb.answer.called
        answer_text = mock_cb.answer.call_args[0][0]
        assert "Ты подарил 1 балл рейтинга" in answer_text
        assert "Рейтинг стал: 5 б." in answer_text

        # Проверяем, что бот уведомил получателя
        assert mock_cb.bot.send_message.called
        msg_args = mock_cb.bot.send_message.call_args[1]
        assert msg_args["chat_id"] == 402
        assert "Даритель Бот" in msg_args["text"]
        assert "(+1 к рейтингу)" in msg_args["text"]

        # Проверяем вызов edit_reply_markup для обновления клавиатуры с новым балансом
        assert mock_cb.message.edit_reply_markup.called

        # Повторная попытка: баланс 0 -> предложение купить суперлайки
        mock_cb.answer.reset_mock()
        mock_cb.message.answer.reset_mock()
        user_donor.superlike_balance = 0

        with patch("bot.utils.dynamic_settings.get_payment_products_catalog", new_callable=AsyncMock) as m_cat, \
             patch("bot.utils.dynamic_settings.get_dynamic_pricing", new_callable=AsyncMock) as m_price:
            m_cat.return_value = []
            m_price.return_value = {}
            await handle_gift_rating(mock_cb, user=user_donor, db=db)
            assert mock_cb.answer.called
            assert "закончились суперлайки" in mock_cb.answer.call_args[0][0].lower()
            assert mock_cb.message.answer.called
