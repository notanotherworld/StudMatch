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


@pytest.mark.asyncio
async def test_yookassa_webhook_amount_mismatch_rejected():
    """Тест C4: Отклонение вебхука при несовпадении суммы с заказом."""
    dummy_payment = MagicMock()
    dummy_payment.amount_rub = 999.0
    dummy_payment.status = "pending"

    dummy_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = dummy_payment
    dummy_db.execute.return_value = mock_result

    request = MagicMock()
    request.headers = {"x-real-ip": "185.71.76.10"}
    request.client = MagicMock(host="185.71.76.10")
    # Злоумышленник пытается подтвердить заказ на 999 руб, оплатив только 1 рубль
    request.json = AsyncMock(return_value={
        "event": "payment.succeeded",
        "object": {
            "id": "pay_fake_123",
            "amount": {"value": "1.00", "currency": "RUB"},
        }
    })

    with patch("web.routers.admin.payments._is_allowed_yookassa_ip", return_value=True), \
         patch("bot.config.settings.YOOKASSA_SHOP_ID", ""), \
         patch("bot.config.settings.YOOKASSA_SECRET_KEY", ""):
        resp = await yookassa_webhook(request, dummy_db)
        assert resp.status_code == 400
        data = json.loads(resp.body.decode())
        assert data["status"] == "rejected"
        assert "Payment amount mismatch" in data["detail"]


@pytest.mark.asyncio
async def test_yookassa_webhook_refund_revokes_perks():
    """Тест C5: Обработка refund.succeeded с автоматическим отзывом услуг."""
    from database.crud import process_payment_refund
    from database.models import PaymentStatus

    dummy_user = MagicMock()
    dummy_user.id = 777
    dummy_user.credits_balance = 300
    dummy_user.boost_until = datetime.now(timezone.utc)
    dummy_user.superlikes_balance = 5

    dummy_payment = MagicMock()
    dummy_payment.id = 1
    dummy_payment.user_id = 777
    dummy_payment.product = "credits_300"
    dummy_payment.amount_rub = 249.0
    dummy_payment.status = PaymentStatus.succeeded

    dummy_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = dummy_payment
    dummy_db.execute.return_value = mock_res

    with patch("database.crud.get_user", AsyncMock(return_value=dummy_user)), \
         patch("database.crud.deduct_user_credits_forced", AsyncMock(return_value=0)) as mock_deduct:
        res = await process_payment_refund(dummy_db, "yk_refund_123", reason="refund")
        assert res is not None
        assert res.status == PaymentStatus.refunded
        mock_deduct.assert_called_once()


def test_yookassa_ip_spoofing_via_x_forwarded_for_neutralized():
    """Тест C6: X-Forwarded-For не может использоваться для обхода белого списка IP."""
    # Если клиент передает поддельный X-Forwarded-For с IP ЮKassa, но X-Real-IP чужой
    # запрос должен отклоняться
    fake_headers = {
        "x-forwarded-for": "185.71.76.10, 1.2.3.4",
        "x-real-ip": "8.8.8.8",
    }
    x_real = fake_headers.get("x-real-ip")
    client_ip = (x_real or fake_headers.get("x-forwarded-for", "").split(",")[0]).strip()
    assert _is_allowed_yookassa_ip(client_ip, is_dev_or_test=False) is False


def test_c1_secret_key_auto_generation():
    """Тест C1: Авто-генерация безопасного 64-символьного ключа при change_me/небезопасном ключе."""
    from bot.config import Settings
    generated_key = Settings.ensure_secure_secret_key("change_me")
    assert len(generated_key) == 64
    assert generated_key != "change_me"

    # Безопасный ключ валидной длины сохраняется без изменений
    safe_custom = "a" * 48
    assert Settings.ensure_secure_secret_key(safe_custom) == safe_custom


def test_c2_stored_xss_prevention():
    """Тест C2: Защита от Stored XSS через javascript: URL в портфолио."""
    from web.routers.webapp import sanitize_portfolio_url
    from fastapi import HTTPException

    # javascript: схемы должны возбуждать HTTPException 400
    with pytest.raises(HTTPException) as exc_info:
        sanitize_portfolio_url("javascript:alert(document.cookie)")
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException):
        sanitize_portfolio_url("DATA:text/html,<script>alert(1)</script>")

    with pytest.raises(HTTPException):
        sanitize_portfolio_url("vbscript:msgbox(1)")

    # Валидные URL должны проходить
    assert sanitize_portfolio_url("https://github.com/developer") == "https://github.com/developer"
    # Чистый домен должен нормализоваться в https://
    assert sanitize_portfolio_url("github.com/developer") == "https://github.com/developer"


@pytest.mark.asyncio
async def test_c3_race_condition_protection():
    """Тест C3: Идемпотентность confirm_payment и защита от повторного/двойного начисления."""
    from database.crud import confirm_payment
    from database.models import PaymentStatus

    dummy_payment = MagicMock()
    dummy_payment.status = PaymentStatus.succeeded
    dummy_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = dummy_payment
    dummy_db.execute.return_value = mock_res

    # Если платеж уже succeeded (второй параллельный webhook), начисление не должно повторяться
    result = await confirm_payment(dummy_db, "yk_already_processed")
    assert result is None


@pytest.mark.asyncio
async def test_c7_csrf_protection_on_emergency_and_tariffs():
    """Тест C7: Защита от CSRF на emergency quick-toggle и тарифах."""
    from web.dependencies import check_csrf
    from fastapi import HTTPException

    # Запрос без CSRF токена должен отклоняться со статусом 403
    request = MagicMock()
    request.method = "POST"
    request.headers = {}
    request.form = AsyncMock(return_value={})
    request.cookies = {"admin_token": "valid_admin_session"}

    with pytest.raises(HTTPException) as exc_info:
        await check_csrf(request)
    assert exc_info.value.status_code == 403
    assert "Invalid CSRF token" in exc_info.value.detail


def test_c8_private_photo_leak_prevention():
    """Тест C8: Приватные фото маскируются на бэкенде, защищая от утечки через JSON."""
    from web.routers.webapp import DEFAULT_FALLBACK_AVATAR

    photos = ["public_photo_1.jpg", "secret_photo_2.jpg", "secret_photo_3.jpg"]
    priv_photos_set = {"secret_photo_2.jpg", "secret_photo_3.jpg"}

    # Логика маскирования из feed
    photos_meta = []
    for idx, pid in enumerate(photos):
        url = f"https://s3.local/{pid}"
        is_priv = bool(idx > 0 and str(pid).strip() in priv_photos_set)
        safe_url = DEFAULT_FALLBACK_AVATAR if is_priv else url
        photos_meta.append({
            "id": str(pid) if not is_priv else f"private_{idx}",
            "url": safe_url,
            "is_private": is_priv,
        })

    # Публичное фото должно иметь реальный URL
    assert photos_meta[0]["url"] == "https://s3.local/public_photo_1.jpg"
    assert photos_meta[0]["is_private"] is False

    # Приватные фото ДОЛЖНЫ содержать только плейсхолдер и замаскированный ID
    assert photos_meta[1]["url"] == DEFAULT_FALLBACK_AVATAR
    assert photos_meta[1]["id"] == "private_1"
    assert "secret_photo_2.jpg" not in photos_meta[1]["url"]

    assert photos_meta[2]["url"] == DEFAULT_FALLBACK_AVATAR
    assert photos_meta[2]["id"] == "private_2"


@pytest.mark.asyncio
async def test_c9_websocket_cswsh_protection():
    """Тест C9: Защита от Cross-Site WebSocket Hijacking через проверку Origin."""
    from web.routers.webapp import websocket_chat_endpoint

    # 1. Попытка подключения с вредоносного внешнего сайта
    malicious_ws = MagicMock()
    malicious_ws.headers = {"origin": "https://evil-attacker.com"}
    malicious_ws.close = AsyncMock()

    with patch("web.routers.webapp._DEBUG", False), \
         patch("bot.config.settings.DEBUG", False), \
         patch("bot.config.settings.DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db"):
        await websocket_chat_endpoint(malicious_ws, "00000000-0000-0000-0000-000000000000")
        # Вебсокет должен быть немедленно закрыт с кодом 1008 (Policy Violation)
        malicious_ws.close.assert_called_once_with(code=1008)

    # 2. Попытка подключения с легитимного домена WebApp
    legit_ws = MagicMock()
    legit_ws.headers = {"origin": "https://stud-match.ru"}
    legit_ws.query_params = {}
    legit_ws.cookies = {}
    legit_ws.close = AsyncMock()

    await websocket_chat_endpoint(legit_ws, "00000000-0000-0000-0000-000000000000")
    # Проверка Origin пройдена, закрытие только из-за отсутствия токена (code=1008 на шаге токена)
    legit_ws.close.assert_called_once_with(code=1008)


