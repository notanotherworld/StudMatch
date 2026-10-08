"""
Фоновый планировщик отложенных и точечных рассылок.
- Проверяет запланированные рассылки (status == 'pending' и scheduled_at <= now()).
- Строит точечные SQL-выборки по полу, режиму, курсу, вузу, навыкам, рейтингу.
- Отправляет сообщения с баннерами и кнопками.
"""
import os
import json
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, URLInputFile, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.session import AsyncSessionLocal
from database.models import User, Profile, BroadcastLog, ModeEnum
from database.crud import MSK_TZ, process_daily_streak_expiration
from bot.config import settings

logger = logging.getLogger(__name__)


def build_recipients_query(filters: dict):
    """
    Строит SQLAlchemy-запрос для выборки ID пользователей по критериям таргетинга.
    """
    query = select(User.id).join(User.profile, isouter=True).where(
        User.is_active == True,
        User.is_fake == False,
    )

    # 1. Верификация
    is_ver_enabled = getattr(settings, "EMAIL_VERIFICATION_ENABLED", False)
    if is_ver_enabled and filters.get("verified_only", False):
        query = query.where(User.email_verified == True)

    # 2. Режим
    mode = filters.get("mode")
    if mode == "career":
        query = query.where(User.mode == ModeEnum.career)
    elif mode == "dating":
        query = query.where(User.mode == ModeEnum.dating)

    # 3. Пол
    gender = filters.get("gender")
    if gender in ("male", "female"):
        query = query.where(Profile.gender == gender)

    # 4. Курс
    year = filters.get("year")
    if year and str(year).isdigit() and int(year) in range(1, 7):
        query = query.where(Profile.year == int(year))

    # 5. ВУЗ
    uni_id = filters.get("university_id")
    if uni_id and str(uni_id).isdigit() and int(uni_id) > 0:
        query = query.where(User.university_id == int(uni_id))

    # 6. Диапазон рейтинга
    min_rating = filters.get("min_rating")
    if min_rating is not None and str(min_rating).strip() != "":
        try:
            query = query.where(Profile.rating_score >= float(min_rating))
        except ValueError:
            pass

    max_rating = filters.get("max_rating")
    if max_rating is not None and str(max_rating).strip() != "":
        try:
            query = query.where(Profile.rating_score <= float(max_rating))
        except ValueError:
            pass

    # 7. Навыки и ключевые слова
    skills_query = filters.get("skills_query", "").strip()
    if skills_query:
        search_pattern = f"%{skills_query}%"
        query = query.where(
            or_(
                Profile.career_custom_skills.ilike(search_pattern),
                Profile.career_goal.ilike(search_pattern),
                Profile.goal.ilike(search_pattern),
                Profile.custom_interests.ilike(search_pattern),
                Profile.major.ilike(search_pattern),
            )
        )

    return query


def build_broadcast_keyboard(button_text: Optional[str], button_url: Optional[str]) -> Optional[InlineKeyboardMarkup]:
    """Создает инлайн-кнопку для рассылки."""
    if not button_text or not button_text.strip():
        return None

    btn_text = button_text.strip()
    btn_url = button_url.strip() if button_url else ""

    builder = InlineKeyboardBuilder()

    if btn_url.startswith("http://") or btn_url.startswith("https://") or btn_url.startswith("tg://"):
        builder.button(text=btn_text, url=btn_url)
    elif btn_url == "profile" or "профиль" in btn_url.lower():
        builder.button(text=btn_text, callback_data="profile:view_dating")
    elif btn_url == "career" or "карьер" in btn_url.lower():
        builder.button(text=btn_text, callback_data="profile:view_career")
    elif btn_url == "top" or "зал" in btn_url.lower():
        builder.button(text=btn_text, callback_data="top:page:1")
    else:
        # По умолчанию открывает меню
        builder.button(text=btn_text, callback_data="update:open")

    builder.adjust(1)
    return builder.as_markup()


def get_media_input(photo_url: Optional[str]):
    """Возвращает InputFile для баннера рассылки."""
    if not photo_url:
        return None
    if photo_url.startswith("http://") or photo_url.startswith("https://"):
        return URLInputFile(photo_url)
    clean_path = photo_url.lstrip("/")
    if not clean_path.startswith("web/"):
        clean_path = os.path.join("web", clean_path)
    if os.path.exists(clean_path):
        return FSInputFile(clean_path)
    return None


async def execute_broadcast_delivery(bot: Bot, broadcast_id: uuid.UUID) -> dict:
    """Выполняет непосредственную рассылку по сохраненной записи BroadcastLog."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(BroadcastLog).where(BroadcastLog.id == broadcast_id))
        blog = res.scalar_one_or_none()
        if not blog:
            return {"sent": 0, "failed": 0}

        # Обновляем статус на processing
        blog.status = "processing"
        await db.commit()

        # Разбираем фильтры
        filters = {}
        if blog.target_filters:
            try:
                filters = json.loads(blog.target_filters)
            except Exception:
                filters = {}

        query = build_recipients_query(filters)
        user_res = await db.execute(query)
        user_ids = [row[0] for row in user_res.all()]

        sent = 0
        failed = 0

        kb = build_broadcast_keyboard(blog.button_text, blog.button_url)
        photo_input = get_media_input(blog.photo_url)
        text_content = blog.text

        logger.info(f"📢 Отправка рассылки #{blog.id} для {len(user_ids)} пользователей...")

        for uid in user_ids:
            try:
                if photo_input:
                    await bot.send_photo(
                        chat_id=uid,
                        photo=photo_input,
                        caption=text_content,
                        parse_mode="HTML",
                        reply_markup=kb,
                    )
                else:
                    await bot.send_message(
                        chat_id=uid,
                        text=text_content,
                        parse_mode="HTML",
                        reply_markup=kb,
                    )
                sent += 1
            except Exception as e:
                logger.debug(f"Ошибка отправки рассылки user_id={uid}: {e}")
                failed += 1

            await asyncio.sleep(0.05)  # 20 msg/s throttle

        # Обновляем запись
        blog.sent_count = sent
        blog.failed_count = failed
        blog.status = "completed"
        await db.commit()

        logger.info(f"✅ Рассылка #{blog.id} завершена: отправлено {sent}, ошибок {failed}")
        return {"sent": sent, "failed": failed}


async def broadcast_scheduler_loop(bot: Bot) -> None:
    """Фоновый воркер: каждые 30 секунд проверяет и запускает запланированные рассылки."""
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    select(BroadcastLog.id).where(
                        BroadcastLog.status == "pending",
                        BroadcastLog.scheduled_at <= now_utc,
                    )
                )
                pending_ids = [row[0] for row in res.all()]

            for bid in pending_ids:
                logger.info(f"⏰ Запуск запланированной рассылки #{bid}...")
                await execute_broadcast_delivery(bot, bid)

        except Exception as e:
            logger.error(f"Ошибка в цикле планировщика рассылок: {e}", exc_info=True)

        await asyncio.sleep(30)


async def streak_reminders_loop(bot: Bot) -> None:
    """
    Фоновый планировщик напоминаний о сохранении стрика в стиле Duolingo:
    - 18:00 МСК: мягкое напоминание пользователям с серией >= 2 дн.
    - 22:30 МСК: срочное напоминание за 1.5 часа до полуночи.
    - 00:05 МСК: списание «Справок от врача» / переход в режим отработки долга на 48ч.
    """
    last_1800_date = None
    last_2230_date = None
    last_0005_date = None

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            now_msk = now_utc.astimezone(MSK_TZ)
            today_date = now_msk.date()

            # 1. 18:00 МСК - Мягкое напоминание
            if now_msk.hour == 18 and now_msk.minute >= 0 and last_1800_date != today_date:
                last_1800_date = today_date
                logger.info("🔥 Запуск рассылки 18:00 МСК для сохранения стриков...")
                async with AsyncSessionLocal() as db:
                    res = await db.execute(
                        select(User).where(
                            User.is_active == True,
                            User.is_fake == False,
                            User.streak_days >= 2,
                        )
                    )
                    users = res.scalars().all()
                    for u in users:
                        last_streak_msk = (
                            u.last_streak_date.astimezone(MSK_TZ).date()
                            if u.last_streak_date and u.last_streak_date.tzinfo
                            else (u.last_streak_date.replace(tzinfo=timezone.utc).astimezone(MSK_TZ).date() if u.last_streak_date else None)
                        )
                        if last_streak_msk == today_date:
                            continue

                        last_act_msk = (
                            u.last_activity_date.astimezone(MSK_TZ).date()
                            if u.last_activity_date and u.last_activity_date.tzinfo
                            else (u.last_activity_date.replace(tzinfo=timezone.utc).astimezone(MSK_TZ).date() if u.last_activity_date else None)
                        )
                        swipes_today = u.today_swipes_count if last_act_msk == today_date else 0
                        needed = max(1, 5 - swipes_today)

                        kb = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="🔥 Зажечь огонёк (лента)", web_app=WebAppInfo(url=settings.webapp_url))
                        ]])
                        text = (
                            f"🔥 <b>Твой огонёк StudMatch ещё не зажжён!</b>\n\n"
                            f"Твоя серия <b>{u.streak_days} дн.</b> под угрозой ⏳\n"
                            f"Сделай всего <b>{needed} свайпов</b> в приложении до полуночи, чтобы сохранить огонь и получить стипендию!"
                        )
                        try:
                            await bot.send_message(chat_id=u.id, text=text, parse_mode="HTML", reply_markup=kb)
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            logger.debug(f"Не удалось отправить 18:00 напоминание стрика {u.id}: {e}")

            # 2. 22:30 МСК - Срочное напоминание за 1.5 часа
            if now_msk.hour == 22 and now_msk.minute >= 30 and last_2230_date != today_date:
                last_2230_date = today_date
                logger.info("⚡️ Запуск срочной рассылки 22:30 МСК для спасения стриков...")
                async with AsyncSessionLocal() as db:
                    res = await db.execute(
                        select(User).where(
                            User.is_active == True,
                            User.is_fake == False,
                            User.streak_days >= 2,
                        )
                    )
                    users = res.scalars().all()
                    for u in users:
                        last_streak_msk = (
                            u.last_streak_date.astimezone(MSK_TZ).date()
                            if u.last_streak_date and u.last_streak_date.tzinfo
                            else (u.last_streak_date.replace(tzinfo=timezone.utc).astimezone(MSK_TZ).date() if u.last_streak_date else None)
                        )
                        if last_streak_msk == today_date:
                            continue

                        last_act_msk = (
                            u.last_activity_date.astimezone(MSK_TZ).date()
                            if u.last_activity_date and u.last_activity_date.tzinfo
                            else (u.last_activity_date.replace(tzinfo=timezone.utc).astimezone(MSK_TZ).date() if u.last_activity_date else None)
                        )
                        swipes_today = u.today_swipes_count if last_act_msk == today_date else 0
                        needed = max(1, 5 - swipes_today)

                        kb = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="⚡️ Спасти стрик прямо сейчас", web_app=WebAppInfo(url=settings.webapp_url))
                        ]])
                        text = (
                            f"⚠️ <b>Срочно! Твой стрик {u.streak_days} дн. сгорит в полночь!</b> 🔥\n\n"
                            f"До спасения серии осталось всего <b>{needed} свайпов</b>.\n"
                            f"Не дай огню угаснуть!"
                        )
                        try:
                            await bot.send_message(chat_id=u.id, text=text, parse_mode="HTML", reply_markup=kb)
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            logger.debug(f"Не удалось отправить 22:30 напоминание стрика {u.id}: {e}")

            # 3. 00:05 МСК - Автоматическая обработка сгорания и заморозок
            if now_msk.hour == 0 and now_msk.minute >= 5 and last_0005_date != today_date:
                last_0005_date = today_date
                logger.info("🌙 Обработка сгорания и заморозки стриков в 00:05 МСК...")
                async with AsyncSessionLocal() as db:
                    res_dict = await process_daily_streak_expiration(db)

                # Уведомляем тех, кого спасла заморозка
                for uid, streak in res_dict.get("frozen", []):
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🔥 Открыть StudMatch", web_app=WebAppInfo(url=settings.webapp_url))
                    ]])
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text=f"🧊 <b>«Справка от врача» спасла твою серию!</b>\n\nТвой стрик <b>{streak} дн.</b> заморожен и сохранён. Зайди сегодня, чтобы продолжить огонь!",
                            parse_mode="HTML",
                            reply_markup=kb,
                        )
                        await asyncio.sleep(0.05)
                    except Exception as e:
                        logger.debug(f"Не удалось отправить уведомление о заморозке {uid}: {e}")

                # Уведомляем тех, у кого серия прервалась, но доступна отработка 48ч
                for uid, streak in res_dict.get("broken", []):
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🩹 Отработать пропуск (25 🎓)", web_app=WebAppInfo(url=settings.webapp_url))
                    ]])
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text=(
                                f"💔 <b>Твоя серия {streak} дн. прервалась...</b>\n\n"
                                f"Но у тебя есть <b>48 часов</b> на «Отработку долга» за 25 🎓, чтобы полностью восстановить серию!\n"
                                f"Не теряй накопленные дни!"
                            ),
                            parse_mode="HTML",
                            reply_markup=kb,
                        )
                        await asyncio.sleep(0.05)
                    except Exception as e:
                        logger.debug(f"Не удалось отправить уведомление о сгорании {uid}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в цикле streak_reminders_loop: {e}", exc_info=True)

        await asyncio.sleep(60)
