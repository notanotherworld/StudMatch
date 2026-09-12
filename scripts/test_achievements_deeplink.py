"""
Тестирование перехода по deep-link из MiniApp:
- Обработка /start achievements при заполненном профиле
- Обработка /start achievements при незаполненном профиле
- Обработка /start premium
- Проверка разметки webapp.html и обработчиков webapp.js
"""
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_AUDIT_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_audit.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram.filters import CommandObject
from bot.states.fsm import AchievementState
from database.models import User, Profile, ModeEnum


@pytest.mark.asyncio
async def test_cmd_start_achievements_with_completed_profile():
    from bot.handlers.start import cmd_start

    message = AsyncMock()
    command = CommandObject(prefix="/", command="start", args="achievements")
    state = AsyncMock()
    user = User(id=777, consent_given=True, mode=ModeEnum.dating)
    user.profile = Profile(id=1, user_id=777, name="Тест", is_complete=True)
    db = AsyncMock()

    with patch("bot.handlers.rating.send_achievement_start", new_callable=AsyncMock) as mock_send_ach:
        await cmd_start(message, command, state, user, db)
        mock_send_ach.assert_awaited_once_with(message, state)


@pytest.mark.asyncio
async def test_cmd_start_achievements_with_incomplete_profile():
    from bot.handlers.start import cmd_start

    message = AsyncMock()
    command = CommandObject(prefix="/", command="start", args="achievements")
    state = AsyncMock()
    user = User(id=888, consent_given=True, mode=ModeEnum.dating)
    user.profile = None
    db = AsyncMock()

    with patch("bot.handlers.profile.start_profile_creation", new_callable=AsyncMock) as mock_start_profile:
        await cmd_start(message, command, state, user, db)
        message.answer.assert_awaited_once()
        assert "Сначала заполни анкету" in message.answer.call_args[0][0]
        mock_start_profile.assert_awaited_once_with(message, state)


@pytest.mark.asyncio
async def test_cmd_start_premium():
    from bot.handlers.start import cmd_start

    message = AsyncMock()
    command = CommandObject(prefix="/", command="start", args="premium")
    state = AsyncMock()
    user = User(id=999, consent_given=True, mode=ModeEnum.dating)
    user.profile = Profile(id=2, user_id=999, name="Премиум", is_complete=True)
    db = AsyncMock()

    with patch("bot.handlers.settings.send_buy_menu", new_callable=AsyncMock) as mock_send_buy:
        await cmd_start(message, command, state, user, db)
        mock_send_buy.assert_awaited_once_with(message, user)


@pytest.mark.asyncio
async def test_send_achievement_start_state_and_markup():
    from bot.handlers.rating import send_achievement_start

    message = AsyncMock()
    state = AsyncMock()

    await send_achievement_start(message, state)

    state.set_state.assert_awaited_once_with(AchievementState.choosing_type)
    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "Добавление достижения" in args[0]
    assert "reply_markup" in kwargs
    # Проверяем, что в клавиатуре есть типы олимпиады, хакатона и т.д.
    kb = kwargs["reply_markup"]
    buttons = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("хакатоне" in text.lower() for text in buttons)
    assert any("победа" in text.lower() for text in buttons)


def test_webapp_html_and_js_contain_button_handlers():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    html_path = os.path.join(base_dir, "web", "templates", "webapp.html")
    js_path = os.path.join(base_dir, "web", "static", "webapp", "webapp.js")

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'id="openBotAchievementsBtn"' in html_content
    assert 'Отправить диплом боту' in html_content
    assert '20260912_13' in html_content
    # Persistent nav checks
    assert 'id="bottomNavWrap"' in html_content
    assert 'bottom-nav-wrap collapsed' not in html_content
    assert 'closeBottomNavBtn' not in html_content
    assert 'navLikesBadge' in html_content
    assert 'navMatchesBadge' in html_content

    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'openBotAchievementsBtn' in js_content
    assert 'request-bot-upload' in js_content
    assert 'start=achievements' in js_content
    assert 'openTelegramLink' in js_content
    assert 'tg.close()' in js_content
    assert 'updateNavBadges' in js_content
    assert 'fetchInitialBadges' in js_content


@pytest.mark.asyncio
async def test_api_request_bot_achievement_upload_success():
    from web.routers.webapp import request_bot_achievement_upload

    user = User(id=111, consent_given=True)
    user.profile = Profile(id=10, user_id=111, name="Студент", is_complete=True)
    db = AsyncMock()

    mock_bot_instance = AsyncMock()
    mock_bot_instance.send_message = AsyncMock()
    mock_bot_instance.session = AsyncMock()
    mock_bot_instance.session.close = AsyncMock()

    with patch("aiogram.Bot", return_value=mock_bot_instance):
        res = await request_bot_achievement_upload(student=user, db=db)
        assert res["status"] == "ok"
        mock_bot_instance.send_message.assert_awaited_once()
        call_kwargs = mock_bot_instance.send_message.call_args[1]
        assert call_kwargs["chat_id"] == 111
        assert "Добавление достижения" in call_kwargs["text"]
        assert call_kwargs["reply_markup"] is not None
        mock_bot_instance.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_request_bot_achievement_upload_need_profile():
    from web.routers.webapp import request_bot_achievement_upload

    user = User(id=222, consent_given=True)
    user.profile = None
    db = AsyncMock()

    res = await request_bot_achievement_upload(student=user, db=db)
    assert res["status"] == "need_profile"
    assert "Сначала заполни анкету" in res["message"]


@pytest.mark.asyncio
async def test_process_type_state_agnostic():
    from bot.handlers.rating import process_type

    callback = AsyncMock()
    callback.data = "ach_type:place_1"
    callback.message = AsyncMock()
    state = AsyncMock()

    await process_type(callback, state)
    state.update_data.assert_awaited_once_with(ach_type="place_1")
    state.set_state.assert_awaited_once_with(AchievementState.waiting_title)
    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    assert "Победа / 1-е место" in callback.message.answer.call_args[0][0]

