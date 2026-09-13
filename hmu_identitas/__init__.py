"""hmu_identitas — satu orang, satu akun, satu sesi, satu saklar nonaktif.

Dipakai produksi, timbangan, gudang2, meja, dan kantor (Tahap 2 rancang ulang
2026, temuan QA X-11, M-06, P-S-05, T-19, P-S-10). Sumbernya repo `core/`,
di-vendor UTUH ke `<repo>/hmu_identitas/` oleh `core/scripts/sinkron.py`
bersama `MANIFEST.sha256` — jangan sunting salinan vendored; ubah di sini,
lalu sinkronkan. Uji penjaga di tiap repo menolak salinan yang basi.

Isinya berlapis, dan lapisannya disengaja:

  · `peran`, `pintu`, `sandi`, `token` — MURNI, pustaka standar saja. Inilah
    yang dipakai aplikasi tipis (Meja, Gudang 2) yang tidak memasang
    SQLAlchemy. `import hmu_identitas` tak boleh menyeret SQLAlchemy.
  · `model`, `masuk` — memetakan tabel dan bicara ke basis data. Hanya
    diimpor aplikasi yang memegang basis data (produksi, timbangan, kantor).

Tabel akun bersama adalah `produksi_akun` — namanya TIDAK diganti (keputusan
pemilik 13 Sep 2026: tabel lama tak diganti nama), tetapi sejak Tahap 2 ia
milik identitas bersama, bukan milik Pos Produksi saja. Peran tinggal di
`users.role`, satu peran per orang; tiap aplikasi memeriksa peran itu di
pintunya sendiri (`pintu.boleh_masuk`).
"""
from __future__ import annotations

from pathlib import Path

VERSI = "1"

AKAR_PAKET = Path(__file__).resolve().parent

from . import peran, pintu  # noqa: E402,F401  (murni)

__all__ = ["VERSI", "AKAR_PAKET", "peran", "pintu"]
