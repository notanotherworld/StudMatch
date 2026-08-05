"""
Throttling middleware — защита от спама.
"""
from typing import Callable, Awaitable, Any
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
import redis.asyncio as aioredis

from bot.config import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничение: не более 1 сообщения в секунду на пользователя."""

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

        user_id = event.from_user.id
        key = f"throttle:{user_id}"
        r = get_redis()

        if await r.exists(key):
            return  # Игнорируем сообщение

        await r.setex(key, int(self.rate_limit), "1")
        return await handler(event, data)


class CallbackThrottlingMiddleware(BaseMiddleware):
    """Ограничение на callback-кнопки: не более 2 нажатий в секунду на пользователя.
    Защищает от спама кнопок оплаты, суперлайков и свайпов (#19).
    """

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        from aiogram.types import CallbackQuery
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user_id = event.from_user.id
        key = f"cb_throttle:{user_id}"
        r = get_redis()

        if await r.exists(key):
            await event.answer("⏳ Не так быстро!", show_alert=False)
            return

        # rate_limit = 0.5s → используем 1s минимум для redis setex (целое число)
        ttl = max(1, int(self.rate_limit))
        await r.setex(key, ttl, "1")
        return await handler(event, data)
