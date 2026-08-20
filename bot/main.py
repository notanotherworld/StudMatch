"""
Точка входа Telegram-бота СтудМэч.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import settings
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware, CallbackThrottlingMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.media_group import MediaGroupMiddleware
from bot.handlers import start, auth, profile, browse, settings as settings_handler, rating, payments, reports as reports_handler, promo as promo_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Синхронизируем схему базы данных (добавление новых колонок)
    from database.session import engine
    from database.migrations import ensure_database_schema
    await ensure_database_schema(engine)

    # FSM хранилище в Redis
    storage = RedisStorage.from_url(settings.REDIS_URL)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Middleware (порядок важен)
    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())
    dp.message.middleware(MediaGroupMiddleware())
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.0))
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(CallbackThrottlingMiddleware(rate_limit=0.5))  # Защита кнопок от спама (#19)
    dp.callback_query.middleware(AuthMiddleware())

    # Роутеры
    dp.include_router(start.router)
    dp.include_router(auth.router)
    dp.include_router(profile.router)
    dp.include_router(browse.router)
    dp.include_router(settings_handler.router)
    dp.include_router(promo_handler.router)
    dp.include_router(rating.router)
    dp.include_router(payments.router)
    dp.include_router(reports_handler.router)

    from aiogram.types import ErrorEvent

    # Глобальный обработчик ошибок
    @dp.error()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"Global error handler caught: {event.exception}", exc_info=event.exception)
        try:
            if event.update and event.update.message:
                await event.update.message.answer(
                    "⚠️ Произошла временная ошибка. Отправь /start чтобы сбросить меню."
                )
            elif event.update and event.update.callback_query:
                await event.update.callback_query.answer("⚠️ Ошибка обработки. Попробуй ещё раз.", show_alert=True)
        except Exception:
            pass
        return True

    logger.info("🚀 СтудМэч запущен!")

    # Запускаем фоновую стартовую рассылку об обновлении платформы
    from bot.services.update_broadcast import run_startup_update_broadcast
    asyncio.create_task(run_startup_update_broadcast(bot))

    # Запускаем фоновый планировщик отложенных рассылок (каждые 30 сек)
    from bot.services.scheduler import broadcast_scheduler_loop
    asyncio.create_task(broadcast_scheduler_loop(bot))

    # Запускаем фоновый мониторинг здоровья системы (раз в час)
    from bot.services.health_checker import hourly_health_monitor
    asyncio.create_task(hourly_health_monitor(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
