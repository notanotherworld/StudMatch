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

    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'openBotAchievementsBtn' in js_content
    assert 'start=achievements' in js_content
    assert 'openTelegramLink' in js_content
    assert 'tg.close()' in js_content
