# Image aplikasi (FastAPI + 3 bot Telegram long-polling).
# Multi-arch: jalan di ARM64 (Oracle Ampere A1) maupun AMD64.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependensi Python. tzdata dibutuhkan ZoneInfo (APP_TIMEZONE=Asia/Jakarta).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt tzdata

# Kode aplikasi + migrasi.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# entrypoint: jalankan migrasi dulu, lalu start server.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
