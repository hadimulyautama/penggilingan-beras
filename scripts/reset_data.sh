#!/usr/bin/env bash
# Kosongkan SEMUA data transaksi (dummy), pertahankan data master.
# Aman: backup otomatis dulu, lalu minta konfirmasi ketik HAPUS.
#
# Lokal (Docker):   ./scripts/reset_data.sh
# Railway/remote:   lihat DEPLOY-RAILWAY.md — jalankan isi scripts/reset_data.sql
#                   lewat `railway connect Postgres`.
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-penggilingan_db}"
DB_USER="${DB_USER:-milluser}"
DB_NAME="${DB_NAME:-penggilingan}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL_FILE="$HERE/reset_data.sql"

if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  echo "[reset] ERROR: kontainer '$DB_CONTAINER' tidak berjalan." >&2
  exit 1
fi

echo "⚠️  Ini MENGHAPUS semua data transaksi (dummy) di DB '$DB_NAME'."
echo "    Dipertahankan: users, warehouses, silos, dryers, suppliers."
echo "    (Backup otomatis dibuat dulu sebelum menghapus.)"
read -r -p "Ketik HAPUS untuk lanjut, lainnya batal: " ans
if [ "$ans" != "HAPUS" ]; then
  echo "Dibatalkan."
  exit 1
fi

echo "[reset] backup dulu untuk jaga-jaga..."
"$HERE/backup.sh" || echo "[reset] (backup dilewati / gagal — lanjut)"

echo "[reset] mengosongkan tabel transaksi..."
docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 < "$SQL_FILE"

echo "[reset] selesai. Data transaksi bersih, data master utuh."
