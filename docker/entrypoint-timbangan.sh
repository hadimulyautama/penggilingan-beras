#!/usr/bin/env bash
# Titik masuk service Timbangan.
#
# SENGAJA TIDAK menjalankan `alembic upgrade head`. Riwayat migrasi hanya milik
# service `app`; dua service yang bermigrasi bersamaan akan berebut skema dan
# bisa saling mengunci. Deploy service ini SELALU setelah service `app`.
#
# Bila tabel `timbangan_*` belum ada, aplikasi akan gagal saat query pertama —
# itu memang perilaku yang diinginkan: lebih baik jelas gagal daripada
# diam-diam membuat skema versi sendiri.
set -e

echo "[timbangan] melewati migrasi — skema dikelola service 'app'."
echo "[timbangan] menjalankan: $*"
exec "$@"
