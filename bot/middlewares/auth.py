"""
Middleware: проверка регистрации и авторизации пользователя.
"""
from typing import Callable, Awaitable, Any
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import get_or_create_user
from database.session import AsyncSessionLocal


class AuthMiddleware(BaseMiddleware):
    """
    1. Создаёт/получает пользователя из БД.
    2. Прокидывает db-сессию и user в данные хэндлера.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        # Получаем from_user из Message или CallbackQuery
        if isinstance(event, (Message, CallbackQuery)):
            tg_user = event.from_user
        else:
            return await handler(event, data)

        async with AsyncSessionLocal() as db:
            user = await get_or_create_user(
                db,
                user_id=tg_user.id,
                tg_username=tg_user.username,
            )
            data["db"] = db
            data["user"] = user
            return await handler(event, data)
