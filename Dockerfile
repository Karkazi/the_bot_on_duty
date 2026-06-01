FROM python:3.12-slim

# При сборке передайте метку, чтобы на сервере проверить версию образа:
# docker buildx build --build-arg BUILD_ID=2026-05-22_15-30 ...
ARG BUILD_ID=unknown
ENV BUILD_ID=${BUILD_ID}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOT_APP_DATA_DIR=/app/data

WORKDIR /app

# системные пакеты (минимум для aiohttp/ssl + tz)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata \
  && rm -rf /var/lib/apt/lists/*

# зависимости
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# код
COPY . /app

# данные состояния отдельно (на сервере примонтируем volume)
RUN mkdir -p /app/data

CMD ["python", "main.py"]