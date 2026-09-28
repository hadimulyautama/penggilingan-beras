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
    #
    # INILAH jenis masuk yang bahan baku: PK beli-luar mendarat di stok Gudang 2
    # (`PkGudang2Intake`), lalu masuk silo, lalu disosoh — jalur yang sama
    # dengan PK hasil giling sendiri, hanya asalnya beda. Ditegaskan pemilik
    # 24 September 2026, dan ditulis di sini justru karena ia mudah tertukar
    # dengan BERAS_MASUK di bawah: keduanya "beras beli dari luar" dalam
    # percakapan, tapi yang satu bahan baku dan yang lain barang jadi.
    "BERAS_PK":     IntakeJenis("pk"),
    # BROKEN_MASUK & BERAS_MASUK: belum dipetakan, tapi TIDAK LAGI menunggu
    # keputusan. Pemilik memutuskan 24 September 2026: keduanya **pembelian**,
    # dan **tidak masuk antrean giling** — beras & broken yang dibeli dari luar
    # sudah jadi, ia tak melewati giling maupun sosoh — bedakan dari BERAS_PK
    # di atas, yang justru bahan baku dan memang menuju silo lalu sosoh.
    #
    # Karena itu ia bukan `PurchaseBatch`: memetakannya ke sana menaruhnya di
    # antrean giling dan di hitungan HPP gabah, dua tempat yang salah. Jalur
    # yang benar adalah pembelian yang mendarat langsung di stok barang jadi
    # Gudang 2, bertanda asal "beli luar" — dan tanda itu wajib, sebab beras
    # beli-luar TIDAK bisa dirunut ke PK sendiri: ia memang tak punya hulu di
    # sini, dan stok yang tidak membedakannya membuat ketelusuran hulu-hilir
    # ikut berbohong untuk barang yang tak punya hulu.
    #
    # Jalurnya belum dibangun (butuh jenis peristiwa & proyeksinya sendiri),
    # jadi sengaja DIBIARKAN kosong: jenis yang dipetakan separuh lebih buruk
    # daripada yang belum dipetakan — tiket akan diterima lalu mendarat di
    # tempat yang salah, sedangkan yang belum dipetakan tergambar sebagai
    # kartu diam di Antrian tunggu dan orang tahu ia harus dikerjakan.
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


def keluar_dari_jenis(jenis_kode: str) -> str | None:
    """Kategori produk untuk sebuah jenis timbang KELUAR, atau None.

    Pasangan `intake_dari_jenis`, dan ia LAHIR 28 September 2026 — sampai hari
    itu `PETA_KELUAR` sudah ada tetapi satu-satunya pemakainya menyusun daftar
    label. Tiket `arah='KELUAR'` karenanya ditimbang di Pos Timbang lalu
    berhenti di situ: tak ada satu pun layar Produksi yang membacanya, sementara
    sisi MASUK punya rantai lengkap dari tiket sampai batch.

    Lebih longgar daripada pasangannya, dan itu disengaja: sisi masuk memakai
    jenisnya untuk MEMILIH TUJUAN (silo mana, tumpukan atau tidak), jadi jenis
    yang tak dipetakan harus ditolak. Di sini jenisnya cuma keterangan pada
    kartu — muatannya sudah ditentukan perintahnya, bukan oleh tiketnya. Tiket
    berjenis asing tetap boleh ditaut; ia cuma tak punya nama kategori.
    """
    return PETA_KELUAR.get((jenis_kode or "").upper())


def is_gabah(jenis_kode: str) -> bool:
    j = intake_dari_jenis(jenis_kode)
    return bool(j and j.model == "gabah")


def is_pk(jenis_kode: str) -> bool:
    j = intake_dari_jenis(jenis_kode)
    return bool(j and j.model == "pk")
