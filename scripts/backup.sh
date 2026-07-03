#!/usr/bin/env bash
# Backup harian database Penggilingan Beras.
# Dump Postgres dari kontainer -> file .sql.gz bertanggal, lalu buang yang lama.
#
# Pakai manual:   ./scripts/backup.sh
# Via cron:       lihat DEPLOY.md Bagian H (Backup otomatis).
set -euo pipefail

# ── Konfigurasi (boleh di-override lewat environment) ──
DB_CONTAINER="${DB_CONTAINER:-penggilingan_db}"
DB_USER="${DB_USER:-milluser}"
DB_NAME="${DB_NAME:-penggilingan}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/penggilingan-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"   # simpan backup 14 hari terakhir

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%F_%H%M)"
OUT="$BACKUP_DIR/penggilingan-$STAMP.sql.gz"

# Gagal lebih awal bila kontainer DB tidak jalan.
if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  echo "[backup] ERROR: kontainer '$DB_CONTAINER' tidak berjalan." >&2
  exit 1
fi

echo "[backup] dump $DB_NAME -> $OUT"
# pg_custom? pakai plain SQL agar mudah di-restore dengan psql.
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$OUT"

# Verifikasi file tidak kosong.
if [ ! -s "$OUT" ]; then
  echo "[backup] ERROR: hasil dump kosong, dihapus." >&2
  rm -f "$OUT"
  exit 1
fi

echo "[backup] OK: $(du -h "$OUT" | cut -f1)"

# Buang backup lebih lama dari RETENTION_DAYS.
find "$BACKUP_DIR" -name 'penggilingan-*.sql.gz' -type f -mtime "+$RETENTION_DAYS" -print -delete \
  | sed 's/^/[backup] hapus lama: /' || true

echo "[backup] selesai. Total backup: $(ls -1 "$BACKUP_DIR"/penggilingan-*.sql.gz 2>/dev/null | wc -l | tr -d ' ') file."
