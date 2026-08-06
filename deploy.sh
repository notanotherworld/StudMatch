#!/bin/bash
# Скрипт прямого деплоя на VPS (если GitHub Actions в очереди / заблокирован)
set -e

echo "📁 Переходим в папку проекта..."
cd ~/apps/bot-univer || cd $(dirname "$0")

echo "⬇️ Получаем последний код из main..."
git fetch origin main
git reset --hard origin/main

echo "🐳 Пересобираем и перезапускаем контейнеры..."
docker compose pull
docker compose up -d --build --remove-orphans

echo "🗄️ Применяем миграции БД..."
docker compose exec -T web alembic upgrade head

echo "🧹 Очистка старых образов..."
docker image prune -f

echo "✅ Деплой успешно завершён!"
