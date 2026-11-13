# Image PadiFlow: FastAPI dan satu pekerja latar dalam satu kontainer.
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
COPY hmu_dokumen ./hmu_dokumen
COPY hmu_core ./hmu_core
COPY hmu_identitas ./hmu_identitas
COPY hmu_tampilan ./hmu_tampilan
COPY app ./app
COPY migrations ./migrations
COPY scripts/portal_pelanggan.py ./scripts/portal_pelanggan.py
COPY scripts/hubungkan_perusahaan_lama.py ./scripts/hubungkan_perusahaan_lama.py
COPY scripts/tetapkan_ruang_perusahaan.py ./scripts/tetapkan_ruang_perusahaan.py
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

# Migrasi sekali sebelum supervisor memulai satu pekerja latar dan web workers.
# Tetap satu replika/kontainer; scheduler tidak digandakan per web worker.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.server"]
