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
DRYER = "dryer"
#: Silo gabah kering sebagai JENIS tujuan — silo mana disebut terpisah
#: ("silo:<id>"). Dulu ada `SILO_A` dan `SILO_B`, dan itu menanam anggapan
#: "silonya dua" ke dalam aturan komoditas — tempat yang paling salah untuk
#: menyimpannya, sebab jumlah silo urusan alat, bukan urusan mutu gabah.
SILO = "silo"
# Tumpukan: dua, dan mana yang dipakai TIDAK disimpan — ia sudah ditentukan
# kondisi gabahnya. Menyimpannya lagi berarti dua tempat yang bisa berbeda.
TUMPUK = "tumpuk"


@dataclass(frozen=True)
class IntakeJenis:
    model: str                       # 'gabah' | 'pk'
    kondisi: str | None = None       # gabah: 'basah' | 'kering'
    jenis_pk: str | None = None      # pk: subtipe bila sudah pasti; None = operator pilih
    tujuan_wajib: str | None = None  # bila diisi → dipaksa (operator tak perlu pilih)
    tujuan_pilihan: tuple[str, ...] = ()  # tujuan yang SAH bila tak wajib


# ── MASUK (intake) ──
PETA_MASUK: dict[str, IntakeJenis] = {
    # Gabah basah: dryer, atau ditumpuk bila dryer sedang penuh. TIDAK boleh
    # langsung ke silo — silo Gudang 1 menampung gabah KERING.
    #
    # Dulu dipaksa ke dryer tanpa pilihan. Itu tidak sesuai kenyataan: dryer
    # hanya menerima satu lot pada satu waktu, dan gabah yang datang saat dryer
    # terisi harus mendarat di suatu tempat. Memaksanya ke dryer hanya membuat
    # pencatatan gagal, bukan membuat gabahnya hilang.
    "GABAH_BASAH":  IntakeJenis("gabah", kondisi="basah",
                                tujuan_pilihan=(DRYER, TUMPUK)),
    # Gabah kering boleh LANGSUNG silo, ke dryer bila masih perlu dikeringkan,
    # atau ditumpuk.
    "GABAH_KERING": IntakeJenis("gabah", kondisi="kering",
                                tujuan_pilihan=(SILO, DRYER, TUMPUK)),
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
