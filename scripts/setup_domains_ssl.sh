#!/usr/bin/env bash
# ==============================================================================
# Скрипт автоматической настройки поддоменов и SSL Let's Encrypt для СтудМэч
#
# Настраиваемые домены:
# - stud-match.ru
# - landing.stud-match.ru
# - hr.stud-match.ru
# - admin.stud-match.ru
# ==============================================================================

set -e

echo "🚀 [1/4] Копирование конфигурации Nginx..."
sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
sudo cp nginx/stud-match.conf /etc/nginx/sites-available/stud-match.conf
sudo ln -sf /etc/nginx/sites-available/stud-match.conf /etc/nginx/sites-enabled/stud-match.conf

echo "🔍 [2/4] Проверка конфигурации Nginx..."
sudo nginx -t

echo "🔄 [3/4] Перезапуск Nginx..."
sudo systemctl reload nginx || sudo service nginx reload

echo "🔐 [4/4] Выпуск SSL-сертификатов Let's Encrypt через Certbot..."
if command -v certbot &> /dev/null; then
    echo "Запуск Certbot для доменов stud-match.ru, landing.stud-match.ru, hr.stud-match.ru, admin.stud-match.ru..."
    sudo certbot --nginx -d stud-match.ru -d landing.stud-match.ru -d hr.stud-match.ru -d admin.stud-match.ru --register-unsafely-without-email --agree-tos --redirect || {
        echo "⚠️ Certbot завершился с предупреждением. Убедитесь, что A-записи доменов направлены на IP сервера."
    }
else
    echo "⚠️ Certbot не установлен. Для автоматического HTTPS выполните:"
    echo "   sudo apt-get update && sudo apt-get install -y certbot python3-certbot-nginx"
    echo "   sudo certbot --nginx -d stud-match.ru -d landing.stud-match.ru -d hr.stud-match.ru -d admin.stud-match.ru"
fi

echo "✅ Настройка доменов завершена!"
