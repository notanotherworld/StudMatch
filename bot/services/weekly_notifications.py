"""
Еженедельная рассылка мотивационных уведомлений студентам по позиции в рейтинге Топ-12 (Яндекс).
"""
import asyncio
import html
import math
import logging
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.session import AsyncSessionLocal
from database.models import User, Profile

logger = logging.getLogger(__name__)


def get_notification_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Загрузить достижение", callback_data="achievement:add")
    builder.button(text="🏆 Зал славы", callback_data="top:page:1")
    builder.adjust(1)
    return builder.as_markup()


async def run_weekly_rank_notifications(bot: Bot) -> dict:
    """
    Рассчитать позиции в топе и отправить персональное уведомление каждому студенту.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Profile)
            .options(selectinload(Profile.user))
            .where(Profile.is_complete == True, Profile.is_visible == True)
            .order_by(Profile.rating_score.desc())
        )
        profiles = list(result.scalars().all())

    if not profiles:
        return {"sent": 0, "failed": 0}

    # Порог баллов для попадания в Топ-12
    top12_index = min(11, len(profiles) - 1)
    top12_benchmark_score = profiles[top12_index].rating_score if profiles else 50.0

    sent = 0
    failed = 0

    for rank, profile in enumerate(profiles, start=1):
        if not profile.user or not profile.user.is_active:
            continue

        user_id = profile.user_id
        score = profile.rating_score

        if rank <= 12:
            text = (
                "🔥 <b>Важно! Компания «Яндекс» смотрит топ-12</b>\n\n"
                "Мы отправили им контакты студентов из Зала славы.\n"
                "Они ищут стажёров-разработчиков прямо сейчас 💼\n\n"
                f"Поздравляем! Ты находишься на <b>{rank}-м месте</b> в Зале славы! 🏆\n\n"
                "Поддерживай свою позицию — обновляй достижения и оставайся в фокусе лучших HR!"
            )
        else:
            gap = max(5, math.ceil(top12_benchmark_score - score) + 1)
            text = (
                "🔥 <b>Важно! Компания «Яндекс» смотрит топ-12</b>\n\n"
                "Мы отправили им контакты студентов из Зала славы.\n"
                "Они ищут стажёров-разработчиков прямо сейчас.\n\n"
                f"Ты пока на <b>{rank}-м месте</b>.\n"
                f"Чтобы попасть в топ-12, тебе не хватает <b>{gap} баллов</b>.\n\n"
                "Загрузи достижение прямо сейчас и стань видимым для HR!"
            )

        try:
            await bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
                reply_markup=get_notification_keyboard(),
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить еженедельное уведомление user_id={user_id}: {e}")
            failed += 1

        await asyncio.sleep(0.05)  # 20 сообщений в секунду (соблюдение лимитов Telegram API)

    logger.info(f"✅ Еженедельная рассылка (Яндекс Топ-12) завершена: отправлено {sent}, ошибок {failed}")
    return {"sent": sent, "failed": failed}


async def weekly_notification_loop(bot: Bot) -> None:
    """
    Фоновый цикл: раз в неделю (7 дней) запускает рассылку.
    """
    await asyncio.sleep(60)  # Задержка 1 мин при старте
    while True:
        try:
            logger.info("⏰ Запуск еженедельной автоматической рассылки Топ-12 (Яндекс)...")
            await run_weekly_rank_notifications(bot)
        except Exception as e:
            logger.error(f"Ошибка в фоновой рассылке: {e}")
        # Ждём 7 дней
        await asyncio.sleep(7 * 86400)
