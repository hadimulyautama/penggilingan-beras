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
  siap=""
  for i in 1 2 3 4 5; do
    if alembic upgrade head; then
      siap="ya"
      echo "[entrypoint] migrasi selesai."
      break
    fi
    echo "[entrypoint] migrasi gagal (percobaan $i/5), tunggu 3 detik..."
    sleep 3
  done

  # ── Gagal berarti BERHENTI, bukan menyala apa adanya ──
  #
  # Sampai 11 September 2026 gelung ini habis lalu uvicorn tetap dijalankan.
  # Layanan yang hidup di atas skema yang belum tentu benar menerima
  # pencatatan dan menyimpannya salah — dan /health tetap "ok", jadi tak ada
  # yang tahu. Jauh lebih baik mati terang-terangan dan terlihat di Railway.
  # Timbangan sudah begini sejak awal; dua yang lain menyusul. Temuan QA X-04.
  if [ -z "$siap" ]; then
    echo "[entrypoint] BERHENTI — migrasi tidak berhasil." >&2
    exit 1
  fi
else
  echo "[entrypoint] LAYANAN=${LAYANAN} — melewati migrasi (skema milik service 'app')."
fi

echo "[entrypoint] menjalankan: $*"
exec "$@"
