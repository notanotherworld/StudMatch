"""
Тестирование отказоустойчивости сетевого слоя бота и обработки сетевых ошибок (Network Resilience Tests):
1. RetryRequestMiddleware — автоматический повтор при TelegramNetworkError.
2. RetryRequestMiddleware — обработка FloodControl (TelegramRetryAfter).
3. create_resilient_bot_session — принудительный IPv4 (AF_INET) и конфигурация таймаутов.
4. MaintenanceMiddleware — безопасный перехват TelegramNetworkError без падения пайплайна бота.
"""
import asyncio
import os
import sys
import socket
from unittest.mock import AsyncMock, MagicMock

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_RESILIENCE")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_audit.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram import Bot
from aiogram.types import Message, User as TgUser
from aiogram.methods import SendMessage
from aiogram.exceptions import TelegramNetworkError
from bot.middlewares.retry import RetryRequestMiddleware, create_resilient_bot_session
from bot.middlewares.maintenance import MaintenanceMiddleware


def test_retry_on_network_error():
    """Проверка автоматического повтора запроса при временном сбое сети."""
    async def _run():
        middleware = RetryRequestMiddleware(max_retries=2, delay=0.01)
        bot = MagicMock(spec=Bot)
        method = SendMessage(chat_id=123, text="Test")

        # Имитируем: 1-я попытка — ошибка сети (таймаут), 2-я попытка — успех
        mock_make_request = AsyncMock(side_effect=[
            TelegramNetworkError(method=method, message="Request timeout error"),
            MagicMock(status="ok", result=MagicMock(message_id=999))
        ])

        resp = await middleware(mock_make_request, bot, method)
        assert resp.status == "ok"
        assert mock_make_request.call_count == 2
        print("  ✅ [1] RetryRequestMiddleware успешно восстанавливается после временного таймаута: УСПЕШНО")

    asyncio.run(_run())


def test_retry_exhausted_raises():
    """Проверка возбуждения ошибки, если лимит повторов исчерпан."""
    async def _run():
        middleware = RetryRequestMiddleware(max_retries=2, delay=0.01)
        bot = MagicMock(spec=Bot)
        method = SendMessage(chat_id=123, text="Test")

        mock_make_request = AsyncMock(side_effect=TelegramNetworkError(method=method, message="Permanent timeout"))

        raised = False
        try:
            await middleware(mock_make_request, bot, method)
        except TelegramNetworkError:
            raised = True

        assert raised is True
        assert mock_make_request.call_count == 3  # 1 исходный + 2 повтора
        print("  ✅ [2] RetryRequestMiddleware корректно эскалирует ошибку после исчерпания попыток: УСПЕШНО")

    asyncio.run(_run())


def test_resilient_session_ipv4():
    """Проверка параметров сессии: явный таймаут и AF_INET (IPv4)."""
    session = create_resilient_bot_session(timeout=25.0, max_retries=2)
    assert session.timeout == 25.0
    assert session._connector_init.get("family") == socket.AF_INET
    assert len(session.middleware._middlewares) == 1
    print("  ✅ [3] create_resilient_bot_session настраивает IPv4 и подключает middleware повторов: УСПЕШНО")


def test_maintenance_middleware_network_error_safety():
    """Проверка, что сетевой сбой при отправке уведомления о техработах не роняет пайплайн."""
    async def _run():
        import bot.middlewares.maintenance as maint_mod

        # Включаем режим техработ через мок
        async def mock_get_setting(key, default=None):
            if key == "maintenance_mode":
                return "true"
            if key == "maintenance_message":
                return "Ведутся работы"
            return default

        maint_mod.get_system_setting = mock_get_setting

        middleware = MaintenanceMiddleware()
        user = TgUser(id=55555, is_bot=False, first_name="Student")
        msg = MagicMock(spec=Message)
        msg.from_user = user
        msg.answer = AsyncMock(side_effect=TelegramNetworkError(method=SendMessage, message="Request timeout error"))

        next_handler = AsyncMock()

        # Вызываем middleware — не должно быть никаких необработанных исключений
        result = await middleware(next_handler, msg, {})
        assert result is None
        assert next_handler.call_count == 0  # Запрос заблокирован техработами
        assert msg.answer.call_count == 1   # Попытка ответить была сделана, ошибка безопасно поймана
        print("  ✅ [4] MaintenanceMiddleware безопасно изолирует сетевые сбои (try/except): УСПЕШНО")

    asyncio.run(_run())


if __name__ == "__main__":
    print("=" * 70)
    print("🛡️ ТЕСТИРОВАНИЕ ОТКАЗОУСТОЙЧИВОСТИ СЕТЕВОГО СЛОЯ БОТА STUDMATCH")
    print("=" * 70)
    test_retry_on_network_error()
    test_retry_exhausted_raises()
    test_resilient_session_ipv4()
    test_maintenance_middleware_network_error_safety()
    print("=" * 70)
    print("🎉 ВСЕ ТЕСТЫ СЕТЕВОЙ ОТКАЗОУСТОЙЧИВОСТИ УСПЕШНО ПРОЙДЕНЫ (4 из 4)!")
    print("=" * 70)
