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


async def get_dynamic_pricing() -> dict:
    """
    Возвращает актуальные цены тарифов и услуг (ЮКасса), синхронизированные с админкой.
    """
    try:
        price_vip = int(await get_system_setting("price_premium_1m", "199"))
    except (ValueError, TypeError):
        price_vip = 199

    try:
        price_boost = int(await get_system_setting("price_boost_24h", "99"))
    except (ValueError, TypeError):
        price_boost = 99

    try:
        price_sl3 = int(await get_system_setting("price_superlike_3", "49"))
    except (ValueError, TypeError):
        price_sl3 = 49

    try:
        price_sl10 = int(await get_system_setting("price_superlike_10", "199"))
    except (ValueError, TypeError):
        price_sl10 = 199

    return {
        "price_premium_1m": price_vip,
        "price_boost_24h": price_boost,
        "price_superlike_3": price_sl3,
        "price_superlike_10": price_sl10,
    }
