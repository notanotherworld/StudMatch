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

echo "🔐 [6/6] Выпуск независимых SSL-сертификатов Let's Encrypt..."
echo "Настройка SSL для stud-match.ru, www.stud-match.ru, landing.stud-match.ru, hr.stud-match.ru, admin.stud-match.ru..."
sudo certbot --nginx \
    -d stud-match.ru \
    -d www.stud-match.ru \
    -d landing.stud-match.ru \
    -d hr.stud-match.ru \
    -d admin.stud-match.ru \
    --cert-name studmatch \
    --register-unsafely-without-email \
    --agree-tos \
    --redirect \
    --expand \
    --non-interactive || {
        echo "⚠️ Certbot завершился с предупреждением."
        echo "Убедитесь, что A-записи доменов (stud-match.ru, www, landing, hr, admin) указывают на IP 159.194.218.148."
    }

echo "🔄 Финальный перезапуск Nginx..."
sudo systemctl reload nginx || sudo service nginx reload

echo "✅ Настройка поддоменов СтудМэч успешно завершена!"
