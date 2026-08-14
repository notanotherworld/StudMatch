#!/usr/bin/env python3
"""
Консольный CLI-инструмент диагностики платформы СтудМэч для сервера VPS.
Запуск: python check_health.py
"""
import sys
import asyncio
import os

# Добавляем директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot
from bot.config import settings
from bot.services.health_checker import run_full_diagnostics

# ANSI цвета для красивого вывода в консоль
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def main():
    print(f"\n{BOLD}🔍 ЗАПУСК ПОЛНОЙ ДИАГНОСТИКИ ПЛАТФОРМЫ СТУДМЭЧ...{RESET}\n")

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        diag = await run_full_diagnostics(bot)
    finally:
        await bot.session.close()

    status = diag["overall_status"]
    status_color = GREEN if status == "OK" else (YELLOW if status == "WARN" else RED)

    print(f"==================================================")
    print(f" Время проверки: {diag['timestamp']}")
    print(f" Общий статус:   {status_color}{BOLD}[{status}]{RESET}")
    print(f" Затрачено:      {diag['total_time_ms']} ms")
    print(f"==================================================\n")

    print(f"{BOLD}СЕРВИСЫ И МОДУЛИ:{RESET}")
    for s in diag["services"]:
        s_status = s["status"]
        if s_status == "OK":
            icon = f"{GREEN}[OK]{RESET}"
        elif s_status == "WARN":
            icon = f"{YELLOW}[WARN]{RESET}"
        else:
            icon = f"{RED}[FAIL]{RESET}"

        lat = f" ({s['latency_ms']} ms)" if s["latency_ms"] is not None else ""
        print(f" {icon} {BOLD}{s['name']}{RESET}{lat}")
        print(f"      ├─ Детали: {s['details']}")
        if s["error"]:
            print(f"      └─ {RED}Ошибка: {s['error']}{RESET}")
        print()

    print(f"==================================================")
    if status == "OK":
        print(f"{GREEN}✅ ВСЕ СЕРВИСЫ РАБОТАЮТ В ШТАТНОМ РЕЖИМЕ!{RESET}\n")
    else:
        print(f"{RED}⚠️ ОБНАРУЖЕНЫ ЗАМЕЧАНИЯ ИЛИ СБОИ В РАБОТЕ.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
