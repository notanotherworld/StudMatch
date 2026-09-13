#!/bin/bash
# Скрипт прямого деплоя на VPS (Smart Deploy: быстрый перезапуск или пересборка при изменении зависимостей)
set -e

echo "📁 Переходим в папку проекта..."
cd ~/apps/bot-univer || cd $(dirname "$0")

echo "⬇️ Получаем последний код из main..."
PREV_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "")
git remote set-url origin https://github.com/notanotherworld/StudMatch.git
git fetch origin main
git reset --hard origin/main
NEW_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "")

echo "📁 Подготавливаем папки..."
mkdir -p web/static/uploads/avatars
chmod -R 777 web/static/uploads 2>/dev/null || true

# Определяем, изменились ли зависимости или файлы контейнеризации
NEED_BUILD=false
if [ -n "$PREV_COMMIT" ] && [ "$PREV_COMMIT" != "$NEW_COMMIT" ]; then
  CHANGED_FILES=$(git diff --name-only "$PREV_COMMIT" "$NEW_COMMIT" 2>/dev/null || true)
  case "$CHANGED_FILES" in
    *requirements.txt*|*Dockerfile*|*docker-compose.yml*)
      echo "📦 Обнаружены изменения в зависимостях или Dockerfile: требуется пересборка..."
      NEED_BUILD=true
      ;;
    *)
      NEED_BUILD=false
      ;;
  esac
fi

if [ "$NEED_BUILD" = "true" ]; then
  echo "🐳 Пересобираем контейнеры (зависимости изменились)..."
  docker compose up -d --build web bot
  echo "🧹 Очистка старых образов..."
  docker image prune -f || true
else
  echo "⚡ Быстрый перезапуск контейнеров (код смонтирован, зависимости без изменений)..."
  docker compose restart web bot || docker compose up -d web bot
fi

echo "⏳ Ожидаем запуск сервисов..."
sleep 3

echo "🗄️ Проверяем миграции БД..."
docker compose exec -T web alembic upgrade head || true

echo "✅ Деплой успешно завершён!"
