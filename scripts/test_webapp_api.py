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
    
    filt = WebAppFiltersRequest(min_age=18, max_age=25, min_year=2, max_year=4, major="IT")
    assert filt.min_age == 18
    assert filt.max_year == 4
    assert filt.major == "IT"
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


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ТЕСТИРОВАНИЕ КРИПТОГРАФИИ И БЕЗОПАСНОСТИ STUDMATCH WEBAPP")
    print("=" * 60)
    test_telegram_init_data_validation()
    test_jwt_student_tokens()
    test_models_and_schemas()
    test_superadmin_security()
    print("=" * 60)
    print("🎉 ВСЕ ТЕСТЫ WEBAPP УСПЕШНО ПРОЙДЕНЫ (10 из 10)!")
    print("=" * 60)


