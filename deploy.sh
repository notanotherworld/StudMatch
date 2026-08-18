#!/bin/bash
# Скрипт прямого деплоя на VPS (если GitHub Actions в очереди / заблокирован)
set -e

echo "📁 Переходим в папку проекта..."
cd ~/apps/bot-univer || cd $(dirname "$0")

echo "⬇️ Получаем последний код из main..."
git remote set-url origin https://github.com/notanotherworld/StudMatch.git
git fetch origin main
git reset --hard origin/main

echo "🐳 Пересобираем и перезапускаем контейнеры..."
docker compose pull
docker compose up -d --build --remove-orphans

echo "⏳ Ожидаем запуск сервисов..."
sleep 4

echo "🗄️ Проверяем миграции БД..."
docker compose exec -T web alembic upgrade head || true

echo "🧹 Очистка старых образов..."
docker image prune -f

echo "✅ Деплой успешно завершён!"
