"""
Middleware режима технических работ и экстренной защиты (Emergency & Anti-Attack Shield).
Позволяет моментально блокировать запросы при атаках, замораживать регистрации и включать техработы.
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot.utils.dynamic_settings import get_system_setting
from bot.config import settings


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        user_id = from_user.id if from_user else None

        # Супер-администраторы обходят экстренную блокировку
        is_admin = False
        if user_id:
            try:
                admin_ids = [int(x.strip()) for x in str(settings.ADMIN_IDS).split(",") if x.strip().isdigit()]
                if user_id in admin_ids or user_id == getattr(settings, "SUPERADMIN_ID", None):
                    is_admin = True
            except Exception:
                pass

        if is_admin:
            return await handler(event, data)

        # 1. 🔴 Экстренная остановка (Emergency Kill Switch)
        is_emergency = await get_system_setting("emergency_mode", "false")
        if is_emergency.lower() in ("true", "1", "yes", "on"):
            msg_text = await get_system_setting(
                "emergency_message",
                "🚨 <b>Сервер временно недоступен</b>\n\nВключён экстренный режим защиты от перегрузки. Доступ будет восстановлен в ближайшее время!",
            )
            if isinstance(event, Message):
                await event.answer(msg_text, parse_mode="HTML")
                return
            elif isinstance(event, CallbackQuery):
                await event.answer("🚨 Экстренный режим защиты платформы активен.", show_alert=True)
                return
            return

        # 2. 🛠 Технические работы (Maintenance Mode)
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
            return

        # 3. 🛑 Заморозка новых регистраций (Freeze Registrations)
        freeze_regs = await get_system_setting("freeze_registrations", "false")
        if freeze_regs.lower() in ("true", "1", "yes", "on"):
            state = data.get("raw_state") or ""
            if "AuthState:" in state or "ProfileState:" in state:
                if isinstance(event, Message):
                    await event.answer(
                        "🛑 <b>Регистрация новых пользователей временно приостановлена администрацией.</b>\n\n"
                        "Пожалуйста, повторите попытку позже.",
                        parse_mode="HTML",
                    )
                    return
                elif isinstance(event, CallbackQuery):
                    await event.answer("🛑 Регистрация временно приостановлена.", show_alert=True)
                    return

        return await handler(event, data)
