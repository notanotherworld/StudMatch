#!/usr/bin/env bash
# ==============================================================================
# Скрипт автоматической настройки поддоменов и SSL Let's Encrypt для СтудМэч
#
# Настраиваемые домены:
# - stud-match.ru
# - www.stud-match.ru
# - landing.stud-match.ru
# - hr.stud-match.ru
# - admin.stud-match.ru
# ==============================================================================

set -e

echo "🚀 [1/6] Проверка и установка Certbot & Nginx..."
if ! command -v nginx &> /dev/null; then
    echo "Установка Nginx..."
    sudo apt-get update && sudo apt-get install -y nginx
fi

if ! command -v certbot &> /dev/null; then
    echo "Установка Certbot..."
    sudo apt-get update && sudo apt-get install -y certbot python3-certbot-nginx
fi

echo "🚀 [2/6] Отключение конфликтующих дефолтных сайтов..."
if [ -f "/etc/nginx/sites-enabled/default" ]; then
    echo "Отключение /etc/nginx/sites-enabled/default для устранения перехвата трафика..."
    sudo rm -f /etc/nginx/sites-enabled/default
fi

echo "🚀 [3/6] Применение конфигурации Nginx для СтудМэч..."
if [ -d "/etc/nginx/sites-available" ]; then
    sudo cp nginx/stud-match.conf /etc/nginx/sites-available/stud-match.conf
    sudo ln -sf /etc/nginx/sites-available/stud-match.conf /etc/nginx/sites-enabled/stud-match.conf
fi

if [ -d "/etc/nginx/conf.d" ]; then
    sudo cp nginx/stud-match.conf /etc/nginx/conf.d/stud-match.conf
fi

echo "🔍 [4/6] Тестирование конфигурации Nginx..."
sudo nginx -t

echo "🔄 [5/6] Перезапуск Nginx..."
sudo systemctl reload nginx || sudo service nginx reload || sudo systemctl restart nginx

echo "🔐 [6/6] Проверка DNS и выпуск независимых SSL-сертификатов Let's Encrypt..."

DOMAINS=("stud-match.ru" "hr.stud-match.ru" "admin.stud-match.ru" "landing.stud-match.ru" "www.stud-match.ru")
VALID_DOMAINS=()

for dom in "${DOMAINS[@]}"; do
    echo -n "🔍 Проверка DNS для $dom... "
    RESOLVED_IP=$(getent ahostsv4 "$dom" 2>/dev/null | head -n 1 | awk '{print $1}')
    if [ -n "$RESOLVED_IP" ]; then
        echo "OK ($RESOLVED_IP)"
        VALID_DOMAINS+=("-d" "$dom")
    else
        echo "НЕ НАЙДЕН в DNS (добавьте A-запись в панели домена)"
    fi
done

if [ ${#VALID_DOMAINS[@]} -gt 0 ]; then
    echo "🚀 Запуск Certbot для доступных доменов: ${VALID_DOMAINS[*]}..."
    sudo certbot --nginx \
        "${VALID_DOMAINS[@]}" \
        --cert-name studmatch \
        --register-unsafely-without-email \
        --agree-tos \
        --redirect \
        --expand \
        --non-interactive || {
            echo "⚠️ Certbot не смог завершить автоматическую настройку."
            echo "Попробуйте вручную: sudo certbot --nginx -d hr.stud-match.ru -d admin.stud-match.ru -d stud-match.ru"
        }
else
    echo "❌ Ни один из доменов не указывает на этот сервер. Сначала добавьте A-записи в панели управления доменом."
fi

echo "🔄 Финальный перезапуск Nginx..."
sudo systemctl reload nginx || sudo service nginx reload

echo "✅ Настройка поддоменов СтудМэч успешно завершена!"
