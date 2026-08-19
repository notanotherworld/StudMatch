"""
Утилита динамических настроек платформы с Redis-кэшированием (0ms latency).
"""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
import redis.asyncio as aioredis

from bot.config import settings
from database.session import AsyncSessionLocal
from database.models import SystemSetting

_redis_pool: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


async def get_system_setting(key: str, default: str = "") -> str:
    """
    Получить значение настройки с 0ms задержкой через Redis cache.
    Если в кэше нет — читает из БД и кэширует на 5 минут.
    """
    cache_key = f"sys_setting:{key}"
    try:
        r = get_redis_client()
        cached = await r.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass

    # Читаем из БД
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()
        val = setting.value if setting else default

    try:
        r = get_redis_client()
        await r.setex(cache_key, 300, val)
    except Exception:
        pass

    return val


async def set_system_setting(key: str, value: str, description: Optional[str] = None) -> None:
    """
    Сохранить системную настройку в БД и мгновенно обновить/сбросить Redis cache.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            insert(SystemSetting)
            .values(key=key, value=value, description=description)
            .on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={"value": value, "description": description or SystemSetting.description},
            )
        )
        await db.execute(stmt)
        await db.commit()

    cache_key = f"sys_setting:{key}"
    try:
        r = get_redis_client()
        await r.delete(cache_key)
        await r.setex(cache_key, 300, value)
    except Exception:
        pass


import json

DEFAULT_PAYMENT_PRODUCTS = [
    {
        "id": "premium_1m",
        "name": "Премиум-подписка 1 мес",
        "emoji": "💎",
        "price": 199,
        "bonus_type": "premium",
        "bonus_value": 30,
        "description": "Безлимитные лайки, фильтры и режим инкогнито",
        "is_active": True,
        "is_default": True,
    },
    {
        "id": "boost_24h",
        "name": "Буст анкеты 24ч",
        "emoji": "⚡️",
        "price": 99,
        "bonus_type": "boost",
        "bonus_value": 24,
        "description": "Показ анкеты первым в ленте на 24 часа",
        "is_active": True,
        "is_default": True,
    },
    {
        "id": "superlike_3",
        "name": "3 суперлайка",
        "emoji": "⭐️",
        "price": 49,
        "bonus_type": "superlikes",
        "bonus_value": 3,
        "description": "Мгновенное уведомление с вашим сообщением",
        "is_active": True,
        "is_default": True,
    },
    {
        "id": "superlike_5",
        "name": "5 суперлайков",
        "emoji": "⭐️",
        "price": 99,
        "bonus_type": "superlikes",
        "bonus_value": 5,
        "description": "Пакет из 5 суперлайков",
        "is_active": True,
        "is_default": True,
    },
    {
        "id": "superlike_10",
        "name": "10 суперлайков",
        "emoji": "⭐️",
        "price": 199,
        "bonus_type": "superlikes",
        "bonus_value": 10,
        "description": "Выгодный пакет из 10 суперлайков",
        "is_active": True,
        "is_default": True,
    },
]


async def get_payment_products_catalog() -> list[dict]:
    """
    Получить полный динамический каталог услуг и тарифов с ценами.
    """
    raw = await get_system_setting("payment_products_catalog", "")
    catalog = []
    if raw:
        try:
            catalog = json.loads(raw)
        except Exception:
            catalog = []

    if not catalog:
        catalog = [dict(p) for p in DEFAULT_PAYMENT_PRODUCTS]

    # Подтягиваем индивидуальные оверрайды цен если они были заданы отдельно
    for item in catalog:
        pid = item.get("id")
        if pid == "premium_1m":
            try:
                item["price"] = int(await get_system_setting("price_premium_1m", str(item.get("price", 199))))
            except Exception:
                pass
        elif pid == "boost_24h":
            try:
                item["price"] = int(await get_system_setting("price_boost_24h", str(item.get("price", 99))))
            except Exception:
                pass
        elif pid == "superlike_3":
            try:
                item["price"] = int(await get_system_setting("price_superlike_3", str(item.get("price", 49))))
            except Exception:
                pass
        elif pid == "superlike_5":
            try:
                item["price"] = int(await get_system_setting("price_superlike_5", str(item.get("price", 99))))
            except Exception:
                pass
        elif pid == "superlike_10":
            try:
                item["price"] = int(await get_system_setting("price_superlike_10", str(item.get("price", 199))))
            except Exception:
                pass

    return catalog


async def save_payment_products_catalog(catalog: list[dict]) -> None:
    """
    Сохраняет каталог услуг и синхронизирует отдельные ключи цен.
    """
    await set_system_setting("payment_products_catalog", json.dumps(catalog, ensure_ascii=False))

    # Синхронизируем базовые ключи для обратной совместимости
    for item in catalog:
        pid = item.get("id")
        price_val = str(item.get("price", 0))
        if pid in ("premium_1m", "boost_24h", "superlike_3", "superlike_5", "superlike_10"):
            await set_system_setting(f"price_{pid}", price_val)


async def get_dynamic_pricing() -> dict:
    """
    Возвращает словарь актуальных цен тарифов и услуг (ЮКасса).
    """
    catalog = await get_payment_products_catalog()
    pricing = {}
    for p in catalog:
        pricing[f"price_{p['id']}"] = int(p.get("price", 0))
        pricing[p["id"]] = int(p.get("price", 0))

    # Дефолтные ключи
    pricing.setdefault("price_premium_1m", 199)
    pricing.setdefault("price_boost_24h", 99)
    pricing.setdefault("price_superlike_3", 49)
    pricing.setdefault("price_superlike_5", 99)
    pricing.setdefault("price_superlike_10", 199)
    return pricing
