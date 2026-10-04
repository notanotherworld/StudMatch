FROM python:3.11-slim

# Системные зависимости с отказоустойчивыми зеркалами
RUN (sed -i 's/deb.debian.org/mirror.yandex.ru/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
     sed -i 's/deb.debian.org/mirror.yandex.ru/g' /etc/apt/sources.list 2>/dev/null || true) && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем зависимости (кешируется отдельным слоем)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Не запускаем от root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
