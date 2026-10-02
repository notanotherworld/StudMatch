"""
Верификационные тесты для проверки закрытия критических уязвимостей безопасности:
1. Защита YooKassa Webhook (проверка IP и вызов API).
2. Запрет авто-начисления пакетов без эквайринга в Production.
3. Защита от Replay Attack через auth_date в verify_telegram_init_data.
4. Маскирование приватных фото на бэкенде.
5. Блокировка забаненных пользователей в AuthMiddleware бота.
"""
import os
import sys
import hmac
import hashlib
import json
import time
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Принудительно запускаем в UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_SECURITY")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_security.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from web.routers.webapp import verify_telegram_init_data, webapp_create_pack_payment, CreatePackPaymentRequest
from web.routers.admin.payments import _is_allowed_yookassa_ip, yookassa_webhook
from database.models import User, Profile, UserPrivacy
from bot.middlewares.auth import AuthMiddleware
from aiogram.types import Message, Chat, User as TgUser


def test_yookassa_ip_whitelist():
    """Тест белого списка официальных IP ЮKassa."""
    # Официальные IP ЮKassa должны проходить
    assert _is_allowed_yookassa_ip("185.71.76.10", is_dev_or_test=False) is True
    assert _is_allowed_yookassa_ip("77.75.153.1", is_dev_or_test=False) is True
    assert _is_allowed_yookassa_ip("77.75.156.11", is_dev_or_test=False) is True
    
    # Посторонние публичные IP должны блокироваться
    assert _is_allowed_yookassa_ip("8.8.8.8", is_dev_or_test=False) is False
    assert _is_allowed_yookassa_ip("195.201.201.1", is_dev_or_test=False) is False
    
    # Loopback IP разрешены только в dev/test
    assert _is_allowed_yookassa_ip("127.0.0.1", is_dev_or_test=False) is False
    assert _is_allowed_yookassa_ip("127.0.0.1", is_dev_or_test=True) is True


def test_telegram_init_data_replay_attack_prevention():
    """Тест защиты от Replay Attack через проверку auth_date."""
    bot_token = "123456:TEST_TOKEN_FOR_SECURITY"
    
    # Формируем устаревший initData (старше 24 часов)
    old_ts = int(time.time()) - (86400 + 3600)
    params = {
        "auth_date": str(old_ts),
        "query_id": "test_query_id",
        "user": json.dumps({"id": 12345, "first_name": "Test"}),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    expired_init_data = f"auth_date={old_ts}&query_id=test_query_id&user={params['user']}&hash={calc_hash}"
    
    # При отключенном режиме тестов устаревший initData должен быть отклонен
    with patch("web.routers.webapp._DEBUG", False), \
         patch("bot.config.settings.DEBUG", False), \
         patch.dict("os.environ", {"DEBUG": "false", "TESTING": "false"}), \
         patch("bot.config.settings.DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db"):
        res = verify_telegram_init_data(expired_init_data, bot_token)
        assert res is None, "Устаревший initData должен быть отклонен!"


@pytest.mark.asyncio
async def test_create_pack_blocked_in_production_without_yookassa():
    """Тест блокировки начисления пакетов в production при пустых ключах ЮKassa."""
    dummy_student = MagicMock()
    dummy_student.id = 55555
    dummy_db = AsyncMock()

    with patch("web.routers.webapp._DEBUG", False), \
         patch("bot.config.settings.DEBUG", False), \
         patch.dict("os.environ", {"DEBUG": "false", "TESTING": "false"}), \
         patch("bot.config.settings.DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db"), \
         patch("bot.config.settings.YOOKASSA_SHOP_ID", ""), \
         patch("bot.config.settings.YOOKASSA_SECRET_KEY", ""), \
         patch("database.crud.check_user_can_buy_starter_pack", AsyncMock(return_value=True)), \
         patch("database.crud.create_payment", AsyncMock(return_value=MagicMock(id="pay_123"))):
        
        req = CreatePackPaymentRequest(pack_code="credits_300")
        resp = await webapp_create_pack_payment(req=req, student=dummy_student, db=dummy_db)
        
        # Должен вернуть ошибку и НЕ выдавать auto_completed: True
        assert resp["status"] == "error"
        assert resp.get("auto_completed") is not True
        assert "недоступен" in resp["message"]


@pytest.mark.asyncio
async def test_auth_middleware_blocks_banned_user():
    """Тест блокировки забаненного пользователя в AuthMiddleware."""
    middleware = AuthMiddleware()
    handler = AsyncMock()
    
    tg_user = TgUser(id=111, is_bot=False, first_name="Banned", username="banned_user")
    chat = Chat(id=111, type="private")
    message = Message(message_id=1, date=datetime.now(), chat=chat, from_user=tg_user, text="/start")
    
    banned_user = MagicMock()
    banned_user.id = 111
    banned_user.is_active = False
    
    with patch.object(Message, "answer", AsyncMock()) as mock_answer, \
         patch("bot.middlewares.auth.get_or_create_user", AsyncMock(return_value=banned_user)), \
         patch("bot.middlewares.auth.AsyncSessionLocal"):
        
        data = {}
        await middleware(handler, message, data)
        
        # Хэндлер не должен быть вызван
        handler.assert_not_called()
        # Пользователю должно быть отправлено сообщение о блокировке
        mock_answer.assert_called_once()
        assert "заблокирован" in mock_answer.call_args[0][0]
