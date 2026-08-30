#!/usr/bin/env bash
# Satu image, beberapa peran. Perannya dipilih variabel LAYANAN, bukan skrip
# terpisah — Railway mengganti CMD tetapi TIDAK mengganti ENTRYPOINT, jadi
# berkas inilah yang selalu berjalan lebih dulu di service mana pun.
#
#   LAYANAN kosong / app  → jalankan migrasi lalu serahkan ke perintah utama
#   LAYANAN=timbangan     → LEWATI migrasi
#
# Riwayat migrasi hanya milik service `app`. Dua service yang bermigrasi
# bersamaan akan berebut skema dan bisa saling mengunci. Bila tabel yang
# dibutuhkan belum ada, service kedua memang harus gagal terang-terangan —
# jauh lebih baik daripada diam-diam membuat skema versi sendiri.
set -e

if [ "${LAYANAN:-app}" = "app" ]; then
  echo "[entrypoint] menjalankan migrasi database (alembic upgrade head)..."
  for i in 1 2 3 4 5; do
    if alembic upgrade head; then
      echo "[entrypoint] migrasi selesai."
      break
    fi
    echo "[entrypoint] migrasi gagal (percobaan $i/5), tunggu 3 detik..."
    sleep 3
  done
else
  echo "[entrypoint] LAYANAN=${LAYANAN} — melewati migrasi (skema milik service 'app')."
fi

echo "[entrypoint] menjalankan: $*"
exec "$@"
