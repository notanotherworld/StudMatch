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
