"""
Middleware повторных попыток запросов к Telegram Bot API (Auto-Retry on Network Timeout).
Обеспечивает устойчивость бота к временным сетевым сбоям, лагам VPS и Flood Control от Telegram.
"""
import asyncio
import logging
import socket
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.methods.base import TelegramMethod, TelegramType, Response

logger = logging.getLogger(__name__)


class RetryRequestMiddleware(BaseRequestMiddleware):
    """
    Автоматически повторяет запрос к Telegram Bot API при сетевых таймаутах
    или временном ограничении частоты запросов (Flood Control / TelegramRetryAfter).
    """

    def __init__(self, max_retries: int = 3, delay: float = 1.0):
        self.max_retries = max_retries
        self.delay = delay

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        method_name = method.__class__.__name__

        for attempt in range(self.max_retries + 1):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as e:
                if attempt < self.max_retries:
                    wait_sec = e.retry_after + 0.5
                    logger.warning(
                        "Telegram FloodControl on %s. Sleeping %.1fs (attempt %d/%d)...",
                        method_name,
                        wait_sec,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(wait_sec)
                else:
                    logger.error(
                        "Telegram FloodControl on %s exceeded retries (%d): %s",
                        method_name,
                        self.max_retries,
                        e,
                    )
                    raise
            except TelegramNetworkError as e:
                if attempt < self.max_retries:
                    sleep_time = self.delay * (1.5 ** attempt)
                    logger.warning(
                        "Telegram network glitch (%s) on %s. Retrying in %.1fs (attempt %d/%d)...",
                        e.message or e,
                        method_name,
                        sleep_time,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    logger.error(
                        "Telegram network error on %s failed after %d attempts: %s",
                        method_name,
                        self.max_retries + 1,
                        e,
                    )
                    raise


def create_resilient_bot_session(timeout: float = 30.0, max_retries: int = 3) -> AiohttpSession:
    """
    Создает устойчивую сессию aiohttp для aiogram:
    1. Устанавливает явный таймаут запроса (30 секунд).
    2. Принудительно задает семейство адресов IPv4 (AF_INET), устраняя задержки и зависания
       aiohappyeyeballs при отсутствии IPv6-маршрутизации в Docker/VPS.
    3. Подключает RetryRequestMiddleware с экспоненциальной задержкой.
    """
    session = AiohttpSession(timeout=timeout)
    # Принудительно используем IPv4 для надежного резолва и коннекта к api.telegram.org в Docker
    session._connector_init["family"] = socket.AF_INET
    session.middleware(RetryRequestMiddleware(max_retries=max_retries, delay=1.0))
    return session
