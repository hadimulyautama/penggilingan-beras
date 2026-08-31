"""Peta JENIS timbangan ↔ perilaku produksi (satu sumber pemetaan).

Timbangan memakai taksonomi jenis sendiri (data-driven, bisa bertambah). Peta ini
menyatukannya dengan model produksi + aturan routing, supaya begitu operator memilih
tiket timbang, produksi LANGSUNG tahu: ini gabah/PK/beras, kondisinya apa, dan boleh ke
mana. Ubah di SATU tempat bila timbangan menambah jenis.

Dua arah:
  • MASUK  → intake (gabah / PK) + aturan penempatan.
  • KELUAR → penjualan output (beras grade / byproduct) — dipakai fase berikutnya.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Tujuan penempatan gabah (harus cocok dengan mini-app & service).
DRYER, SILO_A, SILO_B = "dryer", "silo_a", "silo_b"


@dataclass(frozen=True)
class IntakeJenis:
    model: str                       # 'gabah' | 'pk'
    kondisi: str | None = None       # gabah: 'basah' | 'kering'
    jenis_pk: str | None = None      # pk: subtipe bila sudah pasti; None = operator pilih
    tujuan_wajib: str | None = None  # bila diisi → dipaksa (operator tak perlu pilih)
    tujuan_pilihan: tuple[str, ...] = ()  # tujuan yang SAH bila tak wajib


# ── MASUK (intake) ──
PETA_MASUK: dict[str, IntakeJenis] = {
    # Gabah basah WAJIB ke Dryer dulu (tak boleh langsung silo).
    "GABAH_BASAH":  IntakeJenis("gabah", kondisi="basah",
                                tujuan_wajib=DRYER, tujuan_pilihan=(DRYER,)),
    # Gabah kering boleh LANGSUNG silo atau ke dryer bila masih perlu dikeringkan.
    "GABAH_KERING": IntakeJenis("gabah", kondisi="kering",
                                tujuan_pilihan=(SILO_A, SILO_B, DRYER)),
    # PK dari luar → gudang2. Subtipe (ks/kl/campuran/semi_ks) dipilih operator (timbang
    # tak membedakannya).
    "BERAS_PK":     IntakeJenis("pk"),
    # BROKEN_MASUK & BERAS_MASUK: BELUM dipetakan — menunggu keputusan (beli broken/beras
    # jadi dari luar → modelnya di produksi belum ada). Tambahkan di sini bila sudah pasti.
}


# ── KELUAR (output/penjualan) — dipakai fase berikutnya ──
# Grade beras & byproduct yang dikenal produksi (app.penggilingan.gudang2.polishing).
GRADE_BERAS = ("sayur", "medium", "medsuper", "premium", "beras_b")
BYPRODUCT = ("menir", "broken", "bekatul", "reject")

# jenis_kode KELUAR timbangan → kategori output produksi.
PETA_KELUAR: dict[str, str] = {
    "BERAS": "beras",       # grade ditentukan saat penjualan/stok
    "BROKEN": "broken",
    "MENIR": "menir",
    "BEKATUL": "bekatul",
    "REJECT": "reject",
}


def intake_dari_jenis(jenis_kode: str) -> IntakeJenis | None:
    """Aturan intake untuk sebuah jenis timbang MASUK, atau None bila tak dipetakan."""
    return PETA_MASUK.get((jenis_kode or "").upper())


def is_gabah(jenis_kode: str) -> bool:
    j = intake_dari_jenis(jenis_kode)
    return bool(j and j.model == "gabah")


def is_pk(jenis_kode: str) -> bool:
    j = intake_dari_jenis(jenis_kode)
    return bool(j and j.model == "pk")
