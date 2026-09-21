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

# Kode aplikasi + migrasi. hmu_core = skema master bersama (vendored sementara dari
# repo core; nanti diganti submodule saat app pindah ke produksi/). Paket top-level
# → importable via cwd /app tanpa perlu pip install.
COPY hmu_core ./hmu_core
COPY hmu_identitas ./hmu_identitas
COPY hmu_tampilan ./hmu_tampilan
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Commit yang di-build ke image ini, supaya Pengaturan bisa menyebutnya
# (app/web/versi.py). `.git` sengaja tak ikut ke image, jadi satu-satunya
# sumber saat build adalah variabel yang disuntik Railway — dan variabel
# build hanya terlihat bila dideklarasikan ARG. Kosong bila build tak
# dipicu GitHub; saat itu layar menulis "commit ?", bukan mengarang.
ARG RAILWAY_GIT_COMMIT_SHA
RUN printf '%s' "${RAILWAY_GIT_COMMIT_SHA}" > /app/KOMIT

# entrypoint: jalankan migrasi dulu, lalu start server.
# Port dari $PORT (disuntik Railway/PaaS); default 8000 untuk lokal.
# Bentuk shell agar ${PORT} ter-ekspansi. WAJIB 1 proses / 1 replica —
# banyak proses = banyak polling = bentrok 409 Telegram.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
