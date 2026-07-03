#!/usr/bin/env bash
# Jalankan migrasi database lalu serahkan ke perintah utama (uvicorn).
# depends_on: service_healthy di compose sudah memastikan Postgres siap,
# tapi kita retry alembic beberapa kali untuk jaga-jaga.
set -e

echo "[entrypoint] menjalankan migrasi database (alembic upgrade head)..."
for i in 1 2 3 4 5; do
  if alembic upgrade head; then
    echo "[entrypoint] migrasi selesai."
    break
  fi
  echo "[entrypoint] migrasi gagal (percobaan $i/5), tunggu 3 detik..."
  sleep 3
done

echo "[entrypoint] menjalankan: $*"
exec "$@"
