"""
Throttling middleware — прогрессивная защита от спама и атак (Anti-Flood & Anti-DDoS).
Поддерживает прогрессивную шкалу блокировок (2 мин -> 5 мин -> 15 мин -> 30 мин),
динамический таймер обратного отсчёта и фиксацию нарушителей в базе данных.
"""
import asyncio
import logging
from typing import Callable, Awaitable, Any, Tuple
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
import redis.asyncio as aioredis

from bot.config import settings
from bot.utils.dynamic_settings import get_system_setting

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def format_ban_ttl(ttl_seconds: int) -> str:
    """Форматирует оставшееся время блокировки в человекочитаемый вид."""
    if ttl_seconds <= 0:
        return "менее секунды"
    minutes = ttl_seconds // 60
    seconds = ttl_seconds % 60
    if minutes > 0 and seconds > 0:
        return f"{minutes} мин. {seconds} сек."
    elif minutes > 0:
        return f"{minutes} мин."
    else:
        return f"{seconds} сек."


async def record_user_ban_in_db(user_id: int) -> None:
    """Асинхронно фиксирует факт бана и статус спамера в PostgreSQL."""
    try:
        from database.session import async_session
        from database.models import User
        from sqlalchemy import update, func

        async with async_session() as session:
            stmt = (
                update(User)
                .where(User.id == user_id)
                .values(
                    flood_ban_count=User.flood_ban_count + 1,
                    is_flagged_spammer=True,
                    last_banned_at=func.now(),
                )
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.warning(f"⚠️ Не удалось записать бан в БД для пользователя {user_id}: {e}")


async def apply_progressive_flood_ban(r: aioredis.Redis, user_id: int) -> Tuple[int, str, int]:
    """
    Применяет прогрессивный бан:
    1-й раз: 2 минуты (120 сек)
    2-й раз: 5 минут (300 сек)
    3-й раз: 15 минут (900 сек)
    4-й+ раз: 30 минут (1800 сек)
    """
    level_key = f"flood_ban_level:{user_id}"
    ban_level = await r.incr(level_key)
    # Храним историю нарушений 7 дней для накопления прогрессии
    await r.expire(level_key, 604800)

    if ban_level == 1:
        duration_sec = 120
        duration_text = "2 минуты"
    elif ban_level == 2:
        duration_sec = 300
        duration_text = "5 минут"
    elif ban_level == 3:
        duration_sec = 900
        duration_text = "15 минут"
    else:
        duration_sec = 1800
        duration_text = "30 минут"

    # Устанавливаем блокировку в Redis
    await r.setex(f"temp_ban:{user_id}", duration_sec, str(ban_level))
    # Сбрасываем счётчики нарушений
    await r.delete(f"flood_viols:{user_id}", f"cb_viols:{user_id}")

    # Фиксируем в БД
    asyncio.create_task(record_user_ban_in_db(user_id))

    return duration_sec, duration_text, ban_level


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничение сообщений: прогрессивный бан и динамический таймер."""

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

        user_id = event.from_user.id if event.from_user else 0
        if not user_id:
            return await handler(event, data)

        try:
            r = get_redis()

            # 1. Проверяем, находится ли пользователь в бане
            ban_ttl = await r.ttl(f"temp_ban:{user_id}")
            if ban_ttl > 0:
                # Троттлим предупреждение об активном бане (максимум 1 раз в 4 секунды)
                warn_key = f"warn_throttle:{user_id}"
                if not await r.exists(warn_key):
                    await r.setex(warn_key, 4, "1")
                    time_str = format_ban_ttl(ban_ttl)
                    try:
                        await event.answer(
                            f"⏳ <b>Доступ временно ограничен за частые запросы!</b>\n\n"
                            f"🕒 Разблокировка через: <b>{time_str}</b>\n\n"
                            f"<i>Пожалуйста, дождитесь окончания таймера. Повторные попытки спама увеличивают срок бана "
                            f"(2 мин ➔ 5 мин ➔ 15 мин ➔ 30 мин).</i>"
                        )
                    except Exception:
                        pass
                return  # Сброс запроса

            # 2. Проверяем режим жесткой защиты от атак
            is_strict = await get_system_setting("anti_flood_strict", "false")
            strict_on = is_strict.lower() in ("true", "1", "yes", "on")
            limit_sec = 3 if strict_on else max(1, int(self.rate_limit))
            max_viols = 3 if strict_on else 5

            key = f"throttle:{user_id}"
            if await r.exists(key):
                # Фиксируем нарушение частоты запросов
                viol_key = f"flood_viols:{user_id}"
                viols = await r.incr(viol_key)
                await r.expire(viol_key, 12)

                # При достижении лимита нарушений выписываем прогрессивный бан
                if viols >= max_viols:
                    dur_sec, dur_txt, level = await apply_progressive_flood_ban(r, user_id)
                    time_str = format_ban_ttl(dur_sec)
                    try:
                        await event.answer(
                            f"🚨 <b>Вы временно заблокированы за флуд!</b>\n\n"
                            f"🔒 Блокировка #{level} на: <b>{dur_txt}</b>\n"
                            f"🕒 Разблокировка через: <b>{time_str}</b>\n\n"
                            f"<i>При повторных нарушениях длительность бана автоматически увеличивается.</i>"
                        )
                    except Exception:
                        pass
                return  # Игнорируем спам-сообщение

            await r.setex(key, limit_sec, "1")
        except Exception as e:
            logger.debug(f"ThrottlingMiddleware error: {e}")

        return await handler(event, data)


class CallbackThrottlingMiddleware(BaseMiddleware):
    """Ограничение на callback-кнопки: защита от спама кликов."""

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        if not user_id:
            return await handler(event, data)

        try:
            r = get_redis()

            # 1. Проверяем бан
            ban_ttl = await r.ttl(f"temp_ban:{user_id}")
            if ban_ttl > 0:
                time_str = format_ban_ttl(ban_ttl)
                await event.answer(f"⏳ Бан за спам! Разблокировка через: {time_str}", show_alert=True)
                return

            # 2. Проверяем частоту кликов
            is_strict = await get_system_setting("anti_flood_strict", "false")
            strict_on = is_strict.lower() in ("true", "1", "yes", "on")
            limit_sec = 2 if strict_on else 1
            max_cb_viols = 5 if strict_on else 8

            key = f"cb_throttle:{user_id}"
            if await r.exists(key):
                viol_key = f"cb_viols:{user_id}"
                viols = await r.incr(viol_key)
                await r.expire(viol_key, 10)

                if viols >= max_cb_viols:
                    dur_sec, dur_txt, level = await apply_progressive_flood_ban(r, user_id)
                    time_str = format_ban_ttl(dur_sec)
                    await event.answer(
                        f"🚨 Бан #{level} за спам кликами на {dur_txt}!\nОсталось: {time_str}",
                        show_alert=True,
                    )
                    return

                await event.answer("⏳ Не так быстро!", show_alert=False)
                return

            await r.setex(key, limit_sec, "1")
        except Exception as e:
            logger.debug(f"CallbackThrottlingMiddleware error: {e}")

        return await handler(event, data)
