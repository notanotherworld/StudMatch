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

echo "🚀 [1/5] Проверка и установка Certbot & Nginx..."
if ! command -v nginx &> /dev/null; then
    echo "Установка Nginx..."
    sudo apt-get update && sudo apt-get install -y nginx
fi

if ! command -v certbot &> /dev/null; then
    echo "Установка Certbot..."
    sudo apt-get update && sudo apt-get install -y certbot python3-certbot-nginx
fi

echo "🚀 [2/5] Применение конфигурации Nginx для СтудМэч..."
# Создаем в sites-available/sites-enabled (стандарт Debian/Ubuntu)
if [ -d "/etc/nginx/sites-available" ]; then
    sudo cp nginx/stud-match.conf /etc/nginx/sites-available/stud-match.conf
    sudo ln -sf /etc/nginx/sites-available/stud-match.conf /etc/nginx/sites-enabled/stud-match.conf
fi

# Дублируем в conf.d на случай использования include conf.d/*.conf
if [ -d "/etc/nginx/conf.d" ]; then
    sudo cp nginx/stud-match.conf /etc/nginx/conf.d/stud-match.conf
fi

echo "🔍 [3/5] Тестирование конфигурации Nginx..."
sudo nginx -t

echo "🔄 [4/5] Перезапуск Nginx..."
sudo systemctl reload nginx || sudo service nginx reload || sudo systemctl restart nginx

echo "🔐 [5/5] Выпуск независимых SSL-сертификатов Let's Encrypt..."
echo "Настройка SSL для stud-match.ru, www.stud-match.ru, landing.stud-match.ru, hr.stud-match.ru, admin.stud-match.ru..."
sudo certbot --nginx \
    -d stud-match.ru \
    -d www.stud-match.ru \
    -d landing.stud-match.ru \
    -d hr.stud-match.ru \
    -d admin.stud-match.ru \
    --register-unsafely-without-email \
    --agree-tos \
    --redirect \
    --non-interactive || {
        echo "⚠️ Certbot завершился с предупреждением."
        echo "Проверьте, что в DNS добавлены A-записи для @, www, landing, hr, admin на IP вашего сервера."
    }

echo "🔄 Финальный перезапуск Nginx..."
sudo systemctl reload nginx || sudo service nginx reload

echo "✅ Настройка поддоменов СтудМэч успешно завершена!"
