"""
Сервис рассылки об обновлении бота:
- Отправка уведомления о новых функциях (раздельные анкеты Знакомств и Карьеры, навыки, ссылки на портфолио, улучшенный поиск).
- Автоматический запуск при старте бота (с защитой от повторного спама).
- Ручной запуск из админ-панели.
"""
import os
import asyncio
import logging
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from database.session import AsyncSessionLocal
from database.models import User

logger = logging.getLogger(__name__)

# Версия обновления — меняется при выходе нового крупного релиза
APP_RELEASE_VERSION = "2.4.0-dual-profiles"
VERSION_LOCK_FILE = "/tmp/studmatch_update_broadcast_version.txt" if os.name != "nt" else os.path.join(os.environ.get("TEMP", "."), "studmatch_update_broadcast_version.txt")

UPDATE_TEXT = (
    "🚀 <b>Мы обновили СтудМэч!</b>\n\n"
    "Заходи заценить новые возможности прямо сейчас! 🔥"
)


def get_update_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Открыть СтудМэч", callback_data="update:open")
    builder.adjust(1)
    return builder.as_markup()


async def send_update_announcement(bot: Bot) -> dict:
    """Отправляет уведомление об обновлении всем реальным активным пользователям."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.id).where(
                User.is_active == True,
                User.email_verified == True,
                User.is_fake == False,
            )
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        logger.info("ℹ️ Рассылка обновления: нет активных пользователей.")
        return {"sent": 0, "failed": 0, "total": 0}

    logger.info(f"📢 Запуск рассылки обновления для {len(user_ids)} пользователей...")
    sent = 0
    failed = 0
    kb = get_update_keyboard()

    for uid in user_ids:
        try:
            await bot.send_message(
                chat_id=uid,
                text=UPDATE_TEXT,
                parse_mode="HTML",
                reply_markup=kb,
            )
            sent += 1
        except Exception as e:
            logger.debug(f"Не удалось отправить уведомление user_id={uid}: {e}")
            failed += 1

        await asyncio.sleep(0.05)  # 20 msg/s throttle

    logger.info(f"✅ Рассылка обновления завершена: отправлено {sent}, ошибок {failed} (всего {len(user_ids)})")
    return {"sent": sent, "failed": failed, "total": len(user_ids)}


async def run_startup_update_broadcast(bot: Bot) -> None:
    """
    Фоновый запуск при перезагрузке контейнера бота.
    Проверяет, было ли уже отправлено уведомление для текущей версии релиза,
    чтобы не спамить пользователям при мелких технических перезапусках.
    """
    # Ждём 10 секунд после старта polling
    await asyncio.sleep(10)

    try:
        if os.path.exists(VERSION_LOCK_FILE):
            with open(VERSION_LOCK_FILE, "r", encoding="utf-8") as f:
                last_version = f.read().strip()
            if last_version == APP_RELEASE_VERSION:
                logger.info(f"ℹ️ Уведомление об обновлении {APP_RELEASE_VERSION} уже было отправлено ранее. Пропускаем.")
                return
    except Exception as e:
        logger.warning(f"Ошибка проверки lock-файла рассылки: {e}")

    # Запускаем рассылку
    logger.info(f"🚀 Запуск стартовой рассылки об обновлении версии {APP_RELEASE_VERSION}...")
    res = await send_update_announcement(bot)

    # Сохраняем отправленную версию
    try:
        with open(VERSION_LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(APP_RELEASE_VERSION)
    except Exception as e:
        logger.warning(f"Не удалось записать lock-файл рассылки: {e}")
