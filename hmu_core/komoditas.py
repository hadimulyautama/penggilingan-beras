"""Model komoditas lintas aplikasi.

Identitas produk dipisahkan dari atribut produk. Contohnya, `beras_putih`
memiliki atribut `kualitas`; `beras_pk` adalah jenis beras yang berbeda dan
tidak memakai atribut kualitas beras putih. Hasil samping (broken, menir,
reject, bekatul) juga memiliki identitas jenisnya sendiri.

Modul ini sengaja tidak memuat aturan timbang, stok, kemasan, ataupun proses.
Kedua aplikasi menyimpan aturan operasionalnya sendiri dan mengacu ke kode
komoditas di sini.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class DefinisiAtribut:
    kode: str
    nama: str
    pilihan: tuple[str, ...] = ()
    wajib: bool = False


@dataclass(frozen=True)
class DefinisiKomoditas:
    kode: str
    nama: str
    kelompok: str
    atribut: tuple[DefinisiAtribut, ...] = ()
    turunan_dari: str | None = None
    abstrak: bool = False


@dataclass(frozen=True)
class Kemasan:
    """Spesifikasi kemasan; `None` pada Produk berarti barang curah."""

    jenis_karung: str
    ukuran_kg: int
    tara_per_karung_kg: float
    merek_karung: str | None = None

    def __post_init__(self) -> None:
        if not self.jenis_karung.strip():
            raise ValueError("Jenis karung wajib diisi")
        if self.ukuran_kg <= 0:
            raise ValueError("Ukuran karung harus lebih dari 0 kg")
        if self.tara_per_karung_kg < 0:
            raise ValueError("Tara karung tidak boleh negatif")


@dataclass(frozen=True)
class Produk:
    """Satu jenis komoditas beserta nilai atributnya."""

    komoditas: str
    atribut: Mapping[str, str]
    merek_produk: str | None = None
    kemasan: Kemasan | None = None


@dataclass(frozen=True)
class TransformasiKomoditas:
    """Hubungan bahan masuk dan hasil keluar dari suatu proses."""

    proses: str
    nama: str
    bahan_utama: tuple[str, ...]
    bahan_tambahan: tuple[str, ...] = ()
    hasil: tuple[str, ...] = ()
    kondisi_bahan: str | None = None
    kondisi_hasil: str | None = None


KUALITAS_BERAS_PUTIH = DefinisiAtribut(
    kode="kualitas",
    nama="Kualitas",
    # Nilainya berasal dari master mutu aplikasi operasional, bukan daftar
    # konstanta di model bersama. Nilai baru tidak perlu mengubah kelas ini.
    pilihan=(),
    wajib=True,
)

KATALOG: Mapping[str, DefinisiKomoditas] = MappingProxyType({
    # Kelas induk untuk pengelompokan dan atribut bersama. Kelas abstrak tidak
    # mewakili barang yang dapat ditimbang atau disimpan secara langsung.
    "beras": DefinisiKomoditas("beras", "Beras", "komoditas", abstrak=True),
    "hasil_samping": DefinisiKomoditas(
        "hasil_samping", "Hasil Samping", "komoditas", abstrak=True,
    ),
    "gabah": DefinisiKomoditas(
        "gabah", "Gabah", "bahan_baku",
        (DefinisiAtribut("kondisi", "Kondisi", ("basah", "kering"), True),),
    ),
    "beras_putih": DefinisiKomoditas(
        "beras_putih", "Beras Putih", "beras", (KUALITAS_BERAS_PUTIH,),
        turunan_dari="beras",
    ),
    "beras_pk": DefinisiKomoditas(
        "beras_pk", "Beras PK", "beras", turunan_dari="beras",
    ),
    "beras_olah_ulang": DefinisiKomoditas(
        "beras_olah_ulang", "Beras Olah Ulang", "beras", turunan_dari="beras",
    ),
    "broken": DefinisiKomoditas(
        "broken", "Broken", "hasil_samping", turunan_dari="hasil_samping",
    ),
    "menir": DefinisiKomoditas(
        "menir", "Menir", "hasil_samping", turunan_dari="hasil_samping",
    ),
    "reject": DefinisiKomoditas(
        "reject", "Reject", "hasil_samping", turunan_dari="hasil_samping",
    ),
    "bekatul": DefinisiKomoditas(
        "bekatul", "Bekatul", "hasil_samping", turunan_dari="hasil_samping",
    ),
})

# Rantai proses bersama. Penyosohan dapat menerima PK, beras putih untuk
# disosoh ulang, dan broken sebagai campuran. Hasilnya beras putih (dengan
# kualitas sebagai atribut) serta hasil samping.
TRANSFORMASI_KOMODITAS: Mapping[str, TransformasiKomoditas] = MappingProxyType({
    "pengeringan": TransformasiKomoditas(
        "pengeringan", "Pengeringan", ("gabah",), hasil=("gabah",),
        kondisi_bahan="basah", kondisi_hasil="kering",
    ),
    "giling": TransformasiKomoditas(
        "giling", "Penggilingan", ("gabah",), hasil=("beras_pk",),
        kondisi_bahan="kering",
    ),
    "sosoh": TransformasiKomoditas(
        "sosoh", "Penyosohan", ("beras_pk",),
        bahan_tambahan=("beras_putih", "broken"),
        hasil=("beras_putih", "broken", "menir", "reject", "bekatul"),
    ),
})

# Kode lama yang sudah tersimpan di salah satu aplikasi dipetakan ke identitas
# bersama. Alias adalah jembatan kompatibilitas, bukan jenis komoditas baru.
ALIAS_KOMODITAS: Mapping[str, str] = MappingProxyType({
    "GABAH_BASAH": "gabah",
    "GABAH_KERING": "gabah",
    "BERAS_PK": "beras_pk",
    "PK": "beras_pk",
    "BERAS": "beras_putih",
    "BERAS_MASUK": "beras_putih",
    "BROKEN": "broken",
    "BROKEN_MASUK": "broken",
    "MENIR": "menir",
    "REJECT": "reject",
    "BEKATUL": "bekatul",
    "BERAS_B": "beras_olah_ulang",
})


def jenis_komoditas(kode: str) -> DefinisiKomoditas:
    """Ambil definisi dari kode bersama atau alias kode lama."""
    k = (kode or "").strip().lower()
    k = ALIAS_KOMODITAS.get(k.upper(), k)
    try:
        return KATALOG[k]
    except KeyError as exc:
        raise ValueError(f"Komoditas tidak dikenal: {kode!r}") from exc


def buat_produk(
    kode: str,
    *,
    merek_produk: str | None = None,
    kemasan: Kemasan | None = None,
    **atribut: str,
) -> Produk:
    """Buat identitas produk dan validasi atributnya terhadap jenis barang.

    `buat_produk('beras_putih', kualitas='premium')` valid; kualitas pada
    `beras_pk` atau atribut yang nilainya di luar daftar akan ditolak.
    """
    definisi = jenis_komoditas(kode)
    if definisi.abstrak:
        raise ValueError(f"{definisi.nama} adalah kelas induk, bukan jenis produk")
    definisi_atribut = {a.kode: a for a in definisi.atribut}
    nilai: dict[str, str] = {}
    for nama, mentah in atribut.items():
        if nama not in definisi_atribut:
            raise ValueError(f"Atribut {nama!r} tidak berlaku untuk {definisi.kode}")
        a = definisi_atribut[nama]
        v = str(mentah).strip().lower()
        if not v:
            raise ValueError(f"Nilai atribut {nama!r} tidak boleh kosong")
        if a.pilihan and v not in a.pilihan:
            raise ValueError(f"Nilai {v!r} tidak sah untuk atribut {nama!r}")
        nilai[nama] = v
    for a in definisi.atribut:
        if a.wajib and a.kode not in nilai:
            raise ValueError(f"Atribut {a.nama} wajib untuk {definisi.nama}")
    return Produk(
        definisi.kode,
        MappingProxyType(nilai),
        merek_produk.strip() if merek_produk and merek_produk.strip() else None,
        kemasan,
    )


def kode_komoditas_lama(kode: str) -> str | None:
    """Kembalikan kode bersama untuk kode transaksi/kategori lama."""
    k = (kode or "").strip()
    return ALIAS_KOMODITAS.get(k.upper()) or (k.lower() if k.lower() in KATALOG else None)


def proses_komoditas(kode: str) -> TransformasiKomoditas:
    """Ambil definisi transformasi bersama (`giling` atau `sosoh`)."""
    k = (kode or "").strip().lower()
    try:
        return TRANSFORMASI_KOMODITAS[k]
    except KeyError as exc:
        raise ValueError(f"Proses komoditas tidak dikenal: {kode!r}") from exc
