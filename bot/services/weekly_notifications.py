"""
Еженедельные чередующиеся рассылки:
Неделя A: 🔥 Яндекс Топ-12 (персональный расчёт отставания)
Неделя B: 📢 Карьерный челлендж недели (+60 бонусных баллов)
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


def get_challenge_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Загрузить сертификат", callback_data="achievement:add")
    builder.button(text="🔗 Пригласить друга (+5 б.)", callback_data="settings:ref_link")
    builder.button(text="🏆 Зал славы", callback_data="top:page:1")
    builder.adjust(1)
    return builder.as_markup()


async def run_weekly_rank_notifications(bot: Bot) -> dict:
    """Неделя A: Рассылка Топ-12 (Яндекс)."""
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

    # Порог баллов для попадания в Зал славы Топ-12
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
                "<i>Компании видят топ-50. Чем выше ты в этом списке, тем чаще они пишут тебе первыми. Все получится 🤲🏻</i>"
            )
        else:
            gap = max(5, math.ceil(top12_benchmark_score - score) + 1)
            text = (
                "🔥 <b>Важно! Компания «Яндекс» смотрит топ-12</b>\n\n"
                "Мы отправили им контакты студентов из Зала славы.\n"
                "Они ищут стажёров-разработчиков прямо сейчас.\n\n"
                f"Ты пока на <b>{rank}-м месте</b>.\n"
                f"Чтобы попасть в топ-12, тебе не хватает <b>{gap} баллов</b>.\n\n"
                "Загрузи достижение прямо сейчас и стань видимым для HR!\n\n"
                "<i>Компании видят топ-50. Чем выше ты в этом списке, тем чаще они пишут тебе первыми. Все получится 🤲🏻</i>"
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
            logger.warning(f"Не удалось отправить рассылку user_id={user_id}: {e}")
            failed += 1

        await asyncio.sleep(0.05)

    logger.info(f"✅ Рассылка (Яндекс Топ-12) завершена: отправлено {sent}, ошибок {failed}")
    return {"sent": sent, "failed": failed}


async def run_weekly_challenge_notifications(bot: Bot) -> dict:
    """Неделя B: 📢 Карьерный челлендж недели."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.id).where(User.is_active == True, User.email_verified == True)
        )
        user_ids = [row[0] for row in result.all()]

    text = (
        "📢 <b>Карьерный челлендж недели</b>\n\n"
        "1. Загрузи сертификат о прохождении курса = <b>+40 баллов</b>\n"
        "2. Расскажи о своём проекте в боте = <b>+20 баллов</b>\n"
        "3. Пригласи друга, у которого есть достижения = <b>+5 баллов</b>\n\n"
        "Выполни все три и получи <b>+60 бонусных баллов</b>.\n"
        "Ты поднимешься на 3-5 мест в Зале славы 🎯\n\n"
        "🤲🏻 <i>Компании видят топ-50. Чем выше ты в этом списке, тем чаще они пишут тебе первыми. Все получится!</i>"
    )

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await bot.send_message(
                uid,
                text,
                parse_mode="HTML",
                reply_markup=get_challenge_keyboard(),
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить челлендж user_id={uid}: {e}")
            failed += 1

        await asyncio.sleep(0.05)

    logger.info(f"✅ Челлендж-рассылка завершена: отправлено {sent}, ошибок {failed}")
    return {"sent": sent, "failed": failed}


async def weekly_notification_loop(bot: Bot) -> None:
    """Фоновый цикл: раз в неделю (7 дней) чередует рассылки."""
    await asyncio.sleep(60)
    week_counter = 0
    while True:
        try:
            if week_counter % 2 == 0:
                logger.info("⏰ Запуск еженедельной рассылки (Неделя A: Яндекс Топ-12)...")
                await run_weekly_rank_notifications(bot)
            else:
                logger.info("⏰ Запуск еженедельной рассылки (Неделя B: Карьерный челлендж)...")
                await run_weekly_challenge_notifications(bot)
            week_counter += 1
        except Exception as e:
            logger.error(f"Ошибка в фоновой рассылке: {e}")
        await asyncio.sleep(7 * 86400)
