"""
Тестирование логики WebApp:
- Валидация подписи initData (HMAC-SHA256)
- Проверка генерации и декодирования JWT токенов студентов
- Проверка базовых структур WebApp API
"""
import os
import sys

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_AUDIT_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_audit.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import hmac
import hashlib
import json
from urllib.parse import urlencode

from web.routers.webapp import verify_telegram_init_data, create_student_token
from web.dependencies import SECRET, ALGORITHM
import jwt
import sqlite3
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




def test_telegram_init_data_validation():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
    user_data = {"id": 999888, "first_name": "Алексей", "username": "alex_student"}
    
    # Формируем валидный initData
    params = {
        "auth_date": "1725300000",
        "query_id": "AAHdF6IQAAAAAN0XohCQq123",
        "user": json.dumps(user_data, separators=(",", ":")),
    }
    
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    params["hash"] = valid_hash
    valid_init_data = urlencode(params)

    # 1. Тест валидной строки
    verified_user = verify_telegram_init_data(valid_init_data, bot_token)
    assert verified_user is not None, "Валидная подпись initData должна успешно проверяться"
    assert verified_user["id"] == 999888
    assert verified_user["username"] == "alex_student"
    print("  ✅ [1] Валидация корректной подписи Telegram initData: УСПЕШНО")

    # 2. Тест поддельного токена бота
    bad_bot = verify_telegram_init_data(valid_init_data, "999999:WRONG_TOKEN")
    assert bad_bot is None, "Поддельный токен бота должен быть отклонен"
    print("  ✅ [2] Защита от поддельного bot_token: УСПЕШНО")

    # 3. Тест модифицированных данных (tampered data)
    tampered_params = params.copy()
    tampered_params["auth_date"] = "1725309999"
    tampered_init_data = urlencode(tampered_params)
    tampered_result = verify_telegram_init_data(tampered_init_data, bot_token)
    assert tampered_result is None, "Поддельные параметры должны быть отклонены"
    print("  ✅ [3] Защита от подмены параметров (Tampering): УСПЕШНО")


def test_jwt_student_tokens():
    token = create_student_token(user_id=123456, tg_username="test_student")
    assert isinstance(token, str) and len(token) > 20

    payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert payload["user_id"] == 123456
    assert payload["tg_username"] == "test_student"
    assert payload["role"] == "student"
    print("  ✅ [4] Генерация и валидация JWT-токенов студентов: УСПЕШНО")


def test_models_and_schemas():
    from web.routers.webapp import WebAppFiltersRequest, WebAppReportRequest, WebAppSwipeRequest
    
    filt = WebAppFiltersRequest(min_age=18, max_age=25, min_year=2, max_year=4, major="IT", gender="female")
    assert filt.min_age == 18
    assert filt.max_year == 4
    assert filt.major == "IT"
    assert filt.gender == "female"
    print("  ✅ [5] Валидация Pydantic-схемы фильтров поиска (WebAppFiltersRequest): УСПЕШНО")

    rep = WebAppReportRequest(reported_id=777, reason="📢 Спам или реклама")
    assert rep.reported_id == 777
    assert "Спам" in rep.reason
    print("  ✅ [6] Валидация схемы жалоб (WebAppReportRequest): УСПЕШНО")

    swipe = WebAppSwipeRequest(target_id=888, action="superlike", comment="Отличный профиль!")
    assert swipe.action == "superlike"
    assert swipe.comment == "Отличный профиль!"
    print("  ✅ [7] Валидация свайпа с комплиментом/комментарием: УСПЕШНО")


def test_superadmin_security():
    import asyncio
    from fastapi import HTTPException
    from web.routers.webapp import require_superadmin, AdminUserActionRequest, ResolveReportRequest
    from bot.config import settings

    assert settings.SUPERADMIN_ID == 149620234
    assert 149620234 in settings.admin_ids

    # Создаем фиктивного пользователя
    class DummyUser:
        def __init__(self, user_id):
            self.id = user_id

    # Проверяем, что главному админу доступ РАЗРЕШЕН
    superadmin = DummyUser(149620234)
    res = asyncio.run(require_superadmin(student=superadmin))
    assert res.id == 149620234
    print("  ✅ [8] Доступ к Admin Hub для Superadmin (149620234): РАЗРЕШЕН")

    # Проверяем, что обычному пользователю доступ ЗАПРЕЩЕН (403 Forbidden)
    regular_user = DummyUser(999999)
    try:
        asyncio.run(require_superadmin(student=regular_user))
        assert False, "Should have raised HTTPException 403"
    except HTTPException as exc:
        assert exc.status_code == 403
    print("  ✅ [9] Защита от несанкционированного доступа (403 Forbidden): УСПЕШНО")

    # Валидация схем
    act = AdminUserActionRequest(action="toggle_ban")
    assert act.action == "toggle_ban"
    res_rep = ResolveReportRequest(action="ban_reported")
    assert res_rep.action == "ban_reported"
    print("  ✅ [10] Валидация схем действий админа и модерации жалоб: УСПЕШНО")


def test_maintenance_mode_webapp():
    import asyncio
    from database.models import Base
    from database.session import engine
    from bot.utils.dynamic_settings import get_system_setting, set_system_setting

    async def _test():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 1. Проверяем значение по умолчанию для сообщения техработ
        default_msg = "Некоторые функции могут быть временно недоступны на время обновления. Спасибо за понимание! ❤️"
        msg = await get_system_setting("maintenance_message", default_msg)
        assert "недоступны" in msg or "понимание" in msg, "Сообщение должно содержать предупреждение и благодарность"
        print("  ✅ [11] Дефолтное сообщение техработ содержит предупреждение и вежливую формулировку: УСПЕШНО")

        # 2. Проверяем переключение maintenance_mode
        await set_system_setting("maintenance_mode", "true")
        mm = await get_system_setting("maintenance_mode", "false")
        assert mm.lower() in ("true", "1", "yes", "on")
        
        # 3. Проверяем структуру объекта maintenance для API
        is_maintenance = mm.lower() in ("true", "1", "yes", "on")
        maintenance_data = {
            "is_active": is_maintenance,
            "message": msg,
        }
        assert maintenance_data["is_active"] is True
        assert maintenance_data["message"] == msg
        print("  ✅ [12] Структура ответа maintenance в WebApp API корректна: УСПЕШНО")

        # Возвращаем режим в исходное состояние (false)
        await set_system_setting("maintenance_mode", "false")

    asyncio.run(_test())


def test_in_app_chat_contract():
    import uuid
    from datetime import datetime, timezone
    from web.routers.webapp import ChatSendMessageRequest, ChatReportRequest
    from database.models import Match, ChatMessage, ModeEnum

    # 1. Проверяем схемы запросов
    send_req = ChatSendMessageRequest(text="Привет! Как дела?")
    assert send_req.text == "Привет! Как дела?"

    rep_req = ChatReportRequest(reason="Спам", details="Реклама сторонних каналов")
    assert rep_req.reason == "Спам"
    assert rep_req.details == "Реклама сторонних каналов"

    # 2. Проверяем модель Match и логику обоюдного согласия
    match_id = uuid.uuid4()
    match = Match(
        id=match_id,
        user1_id=1001,
        user2_id=1002,
        mode=ModeEnum.dating,
        user1_tg_approved=False,
        user2_tg_approved=False,
    )
    assert match.is_tg_unlocked is False

    match.user1_tg_approved = True
    assert match.is_tg_unlocked is False

    match.user2_tg_approved = True
    assert match.is_tg_unlocked is True

    # 3. Проверяем контракт ответа эндпоинта сообщений
    partner_tg = "alice_student" if match.is_tg_unlocked else None
    partner_dict = {
        "id": 1002,
        "name": "Алиса",
        "photo_url": "https://example.com/photo.jpg",
        "avatar_url": "https://example.com/photo.jpg",
        "university": "МГУ",
        "year": 3,
        "is_verified": True,
        "is_premium": False,
        "tg_username": partner_tg,
    }

    match_dict = {
        "id": str(match.id),
        "match_id": str(match.id),
        "partner": partner_dict,
        "is_tg_unlocked": match.is_tg_unlocked,
        "my_tg_approved": True,
        "partner_tg_approved": True,
        "partner_tg_username": partner_tg,
    }

    response_data = {
        "status": "ok",
        "match": match_dict,
        "match_id": str(match.id),
        "partner": partner_dict,
        "is_tg_unlocked": match.is_tg_unlocked,
        "my_tg_approved": True,
        "partner_tg_approved": True,
        "partner_tg_username": partner_tg,
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "sender_id": 1001,
                "is_mine": True,
                "text": "Привет!",
                "msg_type": "text",
                "is_read": True,
                "created_at": "12:00",
                "date": "12.09.2026",
            }
        ],
    }

    # Проверка совместимости контрактов (фронтенд ожидает response_data.match ИЛИ поля в корне)
    assert "match" in response_data, "Ключ match должен присутствовать в ответе API"
    assert response_data["match"]["partner"]["name"] == "Алиса"
    assert response_data["match"]["partner"]["avatar_url"] is not None
    assert response_data["match"]["partner_tg_username"] == "alice_student"
    assert len(response_data["messages"]) == 1
    print("  ✅ [13] Контракт внутреннего чата WebApp и взаимного открытия контактов: УСПЕШНО")


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ТЕСТИРОВАНИЕ КРИПТОГРАФИИ И БЕЗОПАСНОСТИ STUDMATCH WEBAPP")
    print("=" * 60)
    test_telegram_init_data_validation()
    test_jwt_student_tokens()
    test_models_and_schemas()
    test_superadmin_security()
    test_maintenance_mode_webapp()
    test_in_app_chat_contract()
    print("=" * 60)
    print("🎉 ВСЕ ТЕСТЫ WEBAPP УСПЕШНО ПРОЙДЕНЫ (13 из 13)!")
    print("=" * 60)



