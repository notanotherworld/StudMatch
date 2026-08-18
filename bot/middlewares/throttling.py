"""
Throttling middleware — защита от спама и атак (Anti-Flood & Anti-DDoS).
"""
from typing import Callable, Awaitable, Any
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
import redis.asyncio as aioredis

from bot.config import settings
from bot.utils.dynamic_settings import get_system_setting

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничение сообщений: в обычном режиме 1 сек, в режиме атаки 3 сек + авто-бан."""

    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        if not user_id:
            return await handler(event, data)

        try:
            r = get_redis()
            # Проверяем временный бан нарушителя
            if await r.exists(f"temp_ban:{user_id}"):
                return  # Полный сброс пакета 0ms без ответа

            # Проверяем режим жесткой защиты от атак
            is_strict = await get_system_setting("anti_flood_strict", "false")
            limit_sec = 3 if is_strict.lower() in ("true", "1", "yes", "on") else max(1, int(self.rate_limit))

            key = f"throttle:{user_id}"
            if await r.exists(key):
                if is_strict.lower() in ("true", "1", "yes", "on"):
                    # Считаем количество нарушений для авто-бана
                    viol_key = f"flood_viols:{user_id}"
                    viols = await r.incr(viol_key)
                    await r.expire(viol_key, 20)
                    if viols >= 4:
                        await r.setex(f"temp_ban:{user_id}", 1800, "1")  # Бан на 30 мин
                return  # Игнорируем спам-сообщение

            await r.setex(key, limit_sec, "1")
        except Exception:
            pass

        return await handler(event, data)


class CallbackThrottlingMiddleware(BaseMiddleware):
    """Ограничение на callback-кнопки: защита от спама кликов."""

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        if not user_id:
            return await handler(event, data)

        try:
            r = get_redis()
            if await r.exists(f"temp_ban:{user_id}"):
                await event.answer("🚫 Доступ временно ограничен за спам.", show_alert=True)
                return

            is_strict = await get_system_setting("anti_flood_strict", "false")
            limit_sec = 2 if is_strict.lower() in ("true", "1", "yes", "on") else 1

            key = f"cb_throttle:{user_id}"
            if await r.exists(key):
                await event.answer("⏳ Не так быстро!", show_alert=False)
                return
            await r.setex(key, limit_sec, "1")
        except Exception:
            pass

        return await handler(event, data)
