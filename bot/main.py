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
from bot.handlers import start, auth, profile, browse, settings as settings_handler, rating, payments, reports as reports_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # FSM хранилище в Redis
    storage = RedisStorage.from_url(settings.REDIS_URL)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Middleware (порядок важен)
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
    dp.include_router(rating.router)
    dp.include_router(payments.router)
    dp.include_router(reports_handler.router)

    logger.info("🚀 СтудМэч запущен!")

    # Запускаем фоновую еженедельную рассылку рейтинга (Яндекс Топ-12)
    from bot.services.weekly_notifications import weekly_notification_loop
    asyncio.create_task(weekly_notification_loop(bot))

    # Запускаем фоновый мониторинг здоровья системы (раз в час)
    from bot.services.health_checker import hourly_health_monitor
    asyncio.create_task(hourly_health_monitor(bot))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
