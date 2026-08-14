"""
Единый сервис диагностики и проверки работоспособности всех модулей системы.
Проверяет: PostgreSQL, Redis, MinIO S3, Telegram Bot API, SMTP Mailer, YooKassa Payments.
"""
import time
import asyncio
import logging
import socket
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from database.session import AsyncSessionLocal
from database.models import User, Profile, Swipe, Match, Achievement, Payment

logger = logging.getLogger(__name__)


async def check_database(db: AsyncSession) -> Dict[str, Any]:
    """Проверка доступности и задержки БД PostgreSQL."""
    start_time = time.perf_counter()
    try:
        # Пинг БД
        await db.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Считаем количество основных сущностей
        users_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
        profiles_count = (await db.execute(select(func.count(Profile.id)))).scalar() or 0
        matches_count = (await db.execute(select(func.count(Match.id)))).scalar() or 0
        swipes_count = (await db.execute(select(func.count(Swipe.id)))).scalar() or 0

        return {
            "name": "PostgreSQL Database",
            "status": "OK",
            "latency_ms": latency_ms,
            "details": f"Пользователей: {users_count}, Анкет: {profiles_count}, Мэтчей: {matches_count}, Свайпов: {swipes_count}",
            "error": None,
        }
    except Exception as e:
        logger.error(f"Health check failed for Database: {e}", exc_info=True)
        return {
            "name": "PostgreSQL Database",
            "status": "ERROR",
            "latency_ms": None,
            "details": "Ошибка подключения к PostgreSQL",
            "error": str(e),
        }


async def check_redis() -> Dict[str, Any]:
    """Проверка доступности и производительности Redis."""
    start_time = time.perf_counter()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        # Выполняем пинг и тестовую запись
        await r.ping()
        test_key = "health_check:test_key"
        await r.setex(test_key, 10, "ok")
        val = await r.get(test_key)
        await r.delete(test_key)
        await r.aclose()

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if val == "ok":
            return {
                "name": "Redis Cache & FSM",
                "status": "OK",
                "latency_ms": latency_ms,
                "details": f"PING & Read/Write OK ({settings.REDIS_URL})",
                "error": None,
            }
        else:
            return {
                "name": "Redis Cache & FSM",
                "status": "WARN",
                "latency_ms": latency_ms,
                "details": "Запись тестового ключа не вернула результат",
                "error": "Key mismatch",
            }
    except Exception as e:
        logger.error(f"Health check failed for Redis: {e}", exc_info=True)
        return {
            "name": "Redis Cache & FSM",
            "status": "ERROR",
            "latency_ms": None,
            "details": f"Не удалось подключиться к Redis ({settings.REDIS_URL})",
            "error": str(e),
        }


async def check_minio() -> Dict[str, Any]:
    """Проверка доступности S3 хранилища MinIO."""
    start_time = time.perf_counter()
    try:
        from bot.utils.minio_client import get_minio_client
        client = get_minio_client()

        # Проверяем существование бакета
        bucket_exists = client.bucket_exists(settings.MINIO_BUCKET)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        if bucket_exists:
            return {
                "name": "MinIO S3 Storage",
                "status": "OK",
                "latency_ms": latency_ms,
                "details": f"Бакет '{settings.MINIO_BUCKET}' доступен ({settings.MINIO_ENDPOINT})",
                "error": None,
            }
        else:
            return {
                "name": "MinIO S3 Storage",
                "status": "WARN",
                "latency_ms": latency_ms,
                "details": f"Бакет '{settings.MINIO_BUCKET}' не найден в MinIO",
                "error": "Bucket missing",
            }
    except Exception as e:
        logger.error(f"Health check failed for MinIO: {e}", exc_info=True)
        return {
            "name": "MinIO S3 Storage",
            "status": "ERROR",
            "latency_ms": None,
            "details": f"Не удалось связаться с MinIO ({settings.MINIO_ENDPOINT})",
            "error": str(e),
        }


async def check_telegram_bot(bot) -> Dict[str, Any]:
    """Проверка валидности токена Telegram Bot API и отклика."""
    start_time = time.perf_counter()
    try:
        me = await bot.get_me()
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "name": "Telegram Bot API",
            "status": "OK",
            "latency_ms": latency_ms,
            "details": f"Бот: @{me.username} (ID: {me.id}, {me.first_name})",
            "error": None,
        }
    except Exception as e:
        logger.error(f"Health check failed for Telegram Bot API: {e}", exc_info=True)
        return {
            "name": "Telegram Bot API",
            "status": "ERROR",
            "latency_ms": None,
            "details": "Не удалось подключиться к Telegram Bot API",
            "error": str(e),
        }


async def check_smtp() -> Dict[str, Any]:
    """Проверка сетевой доступности SMTP-сервера верификации."""
    start_time = time.perf_counter()
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    try:
        # Проверяем сокет
        loop = asyncio.get_event_loop()
        def _connect():
            with socket.create_connection((host, port), timeout=4.0):
                pass

        await loop.run_in_executor(None, _connect)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "name": "SMTP Mailer (Email)",
            "status": "OK",
            "latency_ms": latency_ms,
            "details": f"Сокет {host}:{port} открыт, отправитель: {settings.SMTP_USER}",
            "error": None,
        }
    except Exception as e:
        logger.warning(f"Health check warning for SMTP Mailer: {e}")
        return {
            "name": "SMTP Mailer (Email)",
            "status": "WARN",
            "latency_ms": None,
            "details": f"Соединение с SMTP {host}:{port} недоступно",
            "error": str(e),
        }


async def check_yookassa() -> Dict[str, Any]:
    """Проверка конфигурации платежного шлюза ЮKassa."""
    try:
        shop_id = getattr(settings, "YOOKASSA_SHOP_ID", None)
        secret_key = getattr(settings, "YOOKASSA_SECRET_KEY", None)

        if shop_id and secret_key and str(shop_id).strip() != "":
            return {
                "name": "YooKassa Payments",
                "status": "OK",
                "latency_ms": 0.0,
                "details": f"Shop ID: {shop_id} сконфигурирован",
                "error": None,
            }
        else:
            return {
                "name": "YooKassa Payments",
                "status": "WARN",
                "latency_ms": None,
                "details": "Ключи ЮKassa не заданы в .env (режим симуляции)",
                "error": "Not configured",
            }
    except Exception as e:
        return {
            "name": "YooKassa Payments",
            "status": "WARN",
            "latency_ms": None,
            "details": "Ошибка проверки конфигурации ЮKassa",
            "error": str(e),
        }


async def run_full_diagnostics(bot, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """Запустить полный комплекс проверок всех сервисов системы."""
    start_all = time.perf_counter()

    if db is None:
        async with AsyncSessionLocal() as session:
            db_res = await check_database(session)
    else:
        db_res = await check_database(db)

    redis_res = await check_redis()
    minio_res = await check_minio()
    bot_res = await check_telegram_bot(bot)
    smtp_res = await check_smtp()
    yookassa_res = await check_yookassa()

    services = [db_res, redis_res, minio_res, bot_res, smtp_res, yookassa_res]

    has_error = any(s["status"] == "ERROR" for s in services)
    has_warn = any(s["status"] == "WARN" for s in services)

    overall_status = "ERROR" if has_error else ("WARN" if has_warn else "OK")
    total_time_ms = round((time.perf_counter() - start_all) * 1000, 2)

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "overall_status": overall_status,
        "total_time_ms": total_time_ms,
        "services": services,
    }


async def hourly_health_monitor(bot) -> None:
    """Фоновый периодический мониторинг здоровья системы (раз в час)."""
    logger.info("📡 Запущен фоновый авто-мониторинг состояния системы.")
    await asyncio.sleep(60)  # Даём боту 1 минуту при старте перед первой проверкой

    while True:
        try:
            diag = await run_full_diagnostics(bot)
            if diag["overall_status"] == "ERROR":
                logger.error(f"🚨 ОБНАРУЖЕН СБОЙ СИСТЕМЫ: {diag}")

                # Находим суперадминов в БД и слаем экстренный алерт
                async with AsyncSessionLocal() as db:
                    from database.models import Admin
                    from sqlalchemy import select
                    res = await db.execute(select(Admin).where(Admin.tg_user_id.is_not(None)))
                    admins = res.scalars().all()

                failed_list = [s for s in diag["services"] if s["status"] == "ERROR"]
                failed_str = "\n".join(f"• <b>{s['name']}</b>: {s['error']}" for s in failed_list)

                alert_text = (
                    f"🚨 <b>ЭКСТРЕННЫЙ АЛЕРТ: СБОЙ СИСТЕМЫ!</b>\n\n"
                    f"Время: <code>{diag['timestamp']}</code>\n\n"
                    f"<b>Упавшие сервисы:</b>\n{failed_str}\n\n"
                    f"👉 Запусти <b>/health</b> в боте или проверь консоль VPS (<code>python check_health.py</code>)."
                )

                for admin in admins:
                    try:
                        await bot.send_message(admin.tg_user_id, alert_text, parse_mode="HTML")
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in hourly_health_monitor: {e}", exc_info=True)

        # Интервал проверки: 1 час (3600 секунд)
        await asyncio.sleep(3600)
