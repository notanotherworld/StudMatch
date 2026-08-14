"""
Middleware режима технических работ (Maintenance Mode).
Позволяет включить заглушку техработ через админ-панель без остановки бота.
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot.utils.dynamic_settings import get_system_setting


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Проверяем флаг техработ с 0ms задержкой из Redis
        is_maintenance = await get_system_setting("maintenance_mode", "false")
        if is_maintenance.lower() in ("true", "1", "yes", "on"):
            msg_text = await get_system_setting(
                "maintenance_message",
                "🛠 <b>Бот на техническом обслуживании</b>\n\nМы проводим плановое обновление. Бот скоро возобновит работу!",
            )
            if isinstance(event, Message):
                await event.answer(msg_text, parse_mode="HTML")
                return
            elif isinstance(event, CallbackQuery):
                await event.answer("🛠 Технические работы. Пожалуйста, подождите.", show_alert=True)
                return

        return await handler(event, data)
