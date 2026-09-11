#!/usr/bin/env bash
# Bangun skema LENGKAP dari database KOSONG — satu urutan, yang terbukti jalan.
#
# Temuan QA X-02, 11 September 2026.
#
# Urutan "core dulu" yang tertulis di ARSITEKTUR.md TIDAK jalan: chain produksi
# juga membuat tabel master (0001/0003/0029), tabel kantor_* (0016–0021), dan
# tabel timbangan_* (0022–0026). Menjalankan core lebih dulu membuat
# `warehouses` dua kali dan seluruh bootstrap berhenti di sana.
#
# Yang jalan hanya satu urutan, dan ini dia:
#
#   1. produksi  upgrade head   — membuat hampir semuanya, termasuk master,
#                                 kantor_* baseline, dan timbangan_* 0022–0026
#   2. core      stamp baseline — mengakui tabel master yang sudah dibuat
#                                 produksi; JANGAN upgrade, ia akan mengulang
#   3. kantor    upgrade head   — env.py-nya mengadopsi baseline yang ada
#   4. timbangan stamp 0026 lalu upgrade head
#                               — mengakui warisan, lalu membuat 0027 ke atas
#
# Langkah 4 tak boleh `stamp head`: yang dibuat produksi berhenti di 0026, dan
# stamp sampai HEAD mengaku sudah menjalankan 0027–0029 yang kolomnya tak
# pernah ada (temuan QA X-03).
#
# PEMAKAIAN
#   scripts/bangun_skema.sh postgresql+asyncpg://postgres:pw@127.0.0.1:5432/uji_baru
#
# PAGAR: hanya loopback, dan nama database wajib berawalan "uji_". Skrip ini
# membangun skema dari nol; diarahkan ke database yang salah, ia akan mencoba
# membuat tabel di atas data sungguhan.
set -euo pipefail

URL="${1:-${DATABASE_URL:-}}"
if [ -z "$URL" ]; then
  echo "Pakai: $0 <DATABASE_URL>" >&2
  exit 2
fi

case "$URL" in
  *@127.0.0.1*|*@localhost*) ;;
  *) echo "TOLAK: hanya loopback. Alamat lain bisa saja database yang dipakai orang." >&2
     exit 2 ;;
esac

NAMA="${URL##*/}"
NAMA="${NAMA%%\?*}"
case "$NAMA" in
  uji_*) ;;
  *) echo "TOLAK: nama database harus berawalan 'uji_', bukan '$NAMA'." >&2
     exit 2 ;;
esac

AKAR="$(cd "$(dirname "$0")/../.." && pwd)"
PY_PRODUKSI="$AKAR/produksi/.venv/bin/python"
PY_KANTOR="$AKAR/kantor/.venv/bin/python"
PY_TIMBANGAN="$AKAR/timbangan/.venv/bin/python"

langkah() { echo; echo "── $* ──"; }

langkah "1/4 produksi: upgrade head"
( cd "$AKAR/produksi" && DATABASE_URL="$URL" "$PY_PRODUKSI" -m alembic upgrade head )

langkah "2/4 core: stamp baseline (mengakui master yang sudah dibuat produksi)"
( cd "$AKAR/core" && DATABASE_URL="$URL" "$PY_PRODUKSI" -m alembic stamp 0001_baseline_master )

langkah "3/4 kantor: upgrade head"
( cd "$AKAR/kantor" && DATABASE_URL="$URL" PYTHONPATH=".:$AKAR/kantor/core" \
    "$PY_KANTOR" -m alembic upgrade head )

langkah "4/4 timbangan: stamp 0026 lalu upgrade head"
( cd "$AKAR/timbangan" \
  && DATABASE_URL="$URL" "$PY_TIMBANGAN" -m alembic stamp 0026_timbangan_hapus_pengawas \
  && DATABASE_URL="$URL" "$PY_TIMBANGAN" -m alembic upgrade head )

echo
echo "✅ Skema lengkap terbangun di $NAMA."
