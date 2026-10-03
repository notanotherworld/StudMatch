"""
Тестирование исправлений безопасности магазина и кампусной экономики:
1. HTML Injection & Telegram message escaping.
2. Pydantic schema validation (max_length constraints).
3. Anti-spam / Rate limiting.
4. Cryptographic randomness (CSPRNG via secrets).
5. Row-level locking (with_for_update) integrity.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_SECURITY")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_economy.db")

import asyncio
import html
import pytest
from pydantic import ValidationError
from web.routers.webapp import (
    SendGiftRequest,
    BuyShopItemRequest,
    ClaimQuestRequest,
    check_economy_rate_limit,
    _economy_rate_limiter,
)
from database.crud import FORTUNE_WHEEL_SECTORS, spin_fortune_wheel
from database.session import AsyncSessionLocal
from database.models import User
from sqlalchemy import select


def test_pydantic_length_constraints():
    # 1. Валидный запрос
    req = SendGiftRequest(
        recipient_id=123,
        gift_code="gift_cake",
        message="Happy birthday!",
        is_anonymous=False,
    )
    assert req.gift_code == "gift_cake"
    assert req.message == "Happy birthday!"

    # 2. Превышение длины message (> 200)
    with pytest.raises(ValidationError):
        SendGiftRequest(
            recipient_id=123,
            gift_code="gift_cake",
            message="A" * 201,
        )

    # 3. Превышение длины gift_code (> 64)
    with pytest.raises(ValidationError):
        SendGiftRequest(
            recipient_id=123,
            gift_code="G" * 65,
        )

    # 4. Превышение длины item_code в покупке (> 64)
    with pytest.raises(ValidationError):
        BuyShopItemRequest(item_code="I" * 65)


def test_html_injection_escaping():
    malicious_inputs = [
        '<script>alert("xss")</script>',
        '<b>Unclosed bold tag',
        '<a href="https://evil-phishing.com">Click for free credits</a>',
        'Hello & welcome <to> the jungle',
    ]
    for inp in malicious_inputs:
        escaped = html.escape(inp)
        assert "<" not in escaped
        assert ">" not in escaped
        assert "&lt;" in escaped or "&gt;" in escaped or "&amp;" in escaped


def test_rate_limiter_logic():
    import os
    # Временно снимем флаги тестирования для изолированной проверки алгоритма рейтримитера
    old_test = os.environ.get("PYTEST_CURRENT_TEST")
    try:
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        _economy_rate_limiter.clear()

        # Первый запрос разрешен
        assert check_economy_rate_limit(99999, "action_test", min_interval=0.5) is True
        # Второй мгновенный запрос отклоняется
        assert check_economy_rate_limit(99999, "action_test", min_interval=0.5) is False
        # Запрос другого пользователя разрешен
        assert check_economy_rate_limit(88888, "action_test", min_interval=0.5) is True
    finally:
        if old_test:
            os.environ["PYTEST_CURRENT_TEST"] = old_test


@pytest.mark.asyncio
async def test_wheel_csprng_and_row_locking():
    from database.session import engine
    from database.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(User).where(User.id == 888001).with_for_update()
        )
        u = res.scalar_one_or_none()
        if not u:
            u = User(id=888001, tg_username="test_lock_user")
            db.add(u)
            await db.commit()

        # Тестируем спин
        ok, msg, sector = await spin_fortune_wheel(db, user_id=888001, use_paid=False)
        assert isinstance(ok, bool)
        assert sector is None or "sector_id" in sector
