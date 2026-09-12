"""
Тестирование отключения email-верификации:
- Проверка значения по умолчанию EMAIL_VERIFICATION_ENABLED == False
- Проверка клавиатур my_profile_keyboard и settings_keyboard (кнопка скрыта)
- Проверка текстов приветствия
"""
import os
import sys
import pytest

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_AUDIT_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_audit.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.config import settings
from bot.keyboards.swipe import my_profile_keyboard, settings_keyboard
from bot.handlers.start import WELCOME_TEXT
from database.models import User, ModeEnum


def test_email_verification_default_disabled():
    """Проверяем, что email-верификация по умолчанию выключена."""
    assert settings.EMAIL_VERIFICATION_ENABLED is False, "Верификация по email должна быть отключена по умолчанию"


def test_welcome_text_no_verification_requirement():
    """Проверяем, что приветственный текст не требует обязательной верификации студента."""
    assert "Сначала подтверди, что ты студент" not in WELCOME_TEXT
    assert "Заполни её" in WELCOME_TEXT


def test_my_profile_keyboard_hides_verify_button_when_disabled():
    """Проверяем, что кнопка подтверждения статуса скрыта при EMAIL_VERIFICATION_ENABLED == False."""
    user = User(id=1001, email_verified=False, mode=ModeEnum.dating)
    kb = my_profile_keyboard(user)
    buttons = [btn.text for row in kb.inline_keyboard for btn in row]
    assert not any("Подтвердить статус" in text for text in buttons), (
        f"Кнопка верификации не должна отображаться при выключенной верификации: {buttons}"
    )


def test_settings_keyboard_hides_verify_button_when_disabled():
    """Проверяем, что в настройках кнопка верификации скрыта при EMAIL_VERIFICATION_ENABLED == False."""
    kb = settings_keyboard(current_mode="dating", email_verified=False)
    buttons = [btn.text for row in kb.inline_keyboard for btn in row]
    assert not any("Подтвердить статус" in text for text in buttons), (
        f"Кнопка верификации в настройках не должна отображаться: {buttons}"
    )


def test_keyboards_show_verify_button_when_enabled(monkeypatch):
    """Проверяем, что при EMAIL_VERIFICATION_ENABLED == True кнопка появляется."""
    monkeypatch.setattr(settings, "EMAIL_VERIFICATION_ENABLED", True)
    
    user = User(id=1002, email_verified=False, mode=ModeEnum.dating)
    kb = my_profile_keyboard(user)
    buttons = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("Подтвердить статус" in text for text in buttons), "Кнопка верификации должна появиться при включении"

    kb_settings = settings_keyboard(current_mode="dating", email_verified=False)
    settings_buttons = [btn.text for row in kb_settings.inline_keyboard for btn in row]
    assert any("Подтвердить статус" in text for text in settings_buttons), "Кнопка в настройках должна появиться при включении"


@pytest.mark.asyncio
async def test_show_my_profile_does_not_raise_name_error_when_disabled():
    """Проверяем, что show_my_profile не падает с NameError и не показывает блок верификации при отключении."""
    from unittest.mock import AsyncMock
    from bot.handlers.settings import show_my_profile
    from database.models import Profile

    user = User(id=2001, email_verified=False, mode=ModeEnum.dating, superlike_balance=5)
    user.profile = Profile(name="Тест", age=20, year=2, is_complete=True)
    msg = AsyncMock()
    db = AsyncMock()

    await show_my_profile(msg, user, db)
    assert msg.answer.called or msg.answer_photo.called
    sent_text = msg.answer.call_args[0][0] if msg.answer.called else msg.answer_photo.call_args[1].get("caption", "")
    assert "Верификация: не подтверждена" not in sent_text


@pytest.mark.asyncio
async def test_show_my_profile_includes_verification_status_when_enabled(monkeypatch):
    """Проверяем, что show_my_profile корректно работает при включённой верификации."""
    from unittest.mock import AsyncMock
    from bot.handlers.settings import show_my_profile
    from database.models import Profile

    monkeypatch.setattr(settings, "EMAIL_VERIFICATION_ENABLED", True)
    user = User(id=2002, email_verified=False, mode=ModeEnum.dating, superlike_balance=5)
    user.profile = Profile(name="Тест", age=20, year=2, is_complete=True)
    msg = AsyncMock()
    db = AsyncMock()

    await show_my_profile(msg, user, db)
    assert msg.answer.called or msg.answer_photo.called
    sent_text = msg.answer.call_args[0][0] if msg.answer.called else msg.answer_photo.call_args[1].get("caption", "")
    assert "Верификация: <b>не подтверждена</b>" in sent_text


@pytest.mark.asyncio
async def test_start_verification_callback_when_disabled():
    """Проверяем, что callback запуска верификации сообщает об отключении без NameError."""
    from unittest.mock import AsyncMock
    from bot.handlers.settings import start_verification_callback

    cb = AsyncMock()
    cb.message = AsyncMock()
    state = AsyncMock()
    user = User(id=2003, email_verified=False)

    await start_verification_callback(cb, state, user)
    assert cb.message.answer.called
    assert "временно отключена" in cb.message.answer.call_args[0][0]
