"""Setelan operasional yang boleh diubah Admin dari layar, tanpa deploy ulang.

Urutan kemenangan nilai:

    baris di `timbangan_config`  →  variabel environment  →  bawaan kode

Baris yang tidak ada berarti "pakai environment", jadi mengembalikan satu
setelan ke bawaannya cukup dengan menghapus barisnya.

**Batas bawah dan atas bukan hiasan.** Parameter di sini menentukan angka mana
yang ditolak sistem sebagai mustahil; kapasitas jembatan yang salah ketik jadi
2.000 kg akan menolak setiap truk yang datang. Karena itu setiap nilai
divalidasi sebelum tersimpan, dan setiap perubahan menulis jejak audit.

Yang SENGAJA tidak ada di sini: ambang kontrol, tara, dan aturan komoditas.
Semua itu milik `timbangan_jenis` — merevisinya berarti merevisi cara
perusahaan menilai kejujuran timbangan, dan itu lewat revisi SOP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan.config import tsettings
from app.timbangan.models import TimbanganAkun, TimbanganConfig


class SetelanError(ValueError):
    """Nilai yang diminta di luar batas yang masuk akal."""


@dataclass(frozen=True)
class Definisi:
    kunci: str
    nama: str
    satuan: str
    arti: str
    env: str
    bawaan: Callable[[], float]
    minimum: float
    maksimum: float
    desimal: int = 0

    def format(self, nilai: float) -> str:
        return f"{nilai:.{self.desimal}f}".rstrip("0").rstrip(".") \
            if self.desimal else f"{nilai:.0f}"

    def periksa(self, nilai: float) -> float:
        if nilai != nilai or nilai in (float("inf"), float("-inf")):
            raise SetelanError(f"{self.nama}: bukan angka yang sah.")
        if not (self.minimum <= nilai <= self.maksimum):
            raise SetelanError(
                f"{self.nama} harus antara {self.format(self.minimum)} dan "
                f"{self.format(self.maksimum)} {self.satuan}."
            )
        return nilai


DAFTAR: tuple[Definisi, ...] = (
    Definisi(
        kunci="kapasitas_jembatan_kg",
        nama="Kapasitas jembatan timbang",
        satuan="kg",
        arti="Angka timbang di atas ini ditolak sebagai mustahil.",
        env="TIMBANGAN_KAPASITAS_KG",
        bawaan=lambda: tsettings.kapasitas_jembatan_kg,
        # Di bawah 1 ton tidak ada jembatan timbang truk; di atas 200 ton tidak
        # ada di Indonesia. Keduanya menandakan salah ketik, bukan niat.
        minimum=1_000, maksimum=200_000,
    ),
    Definisi(
        kunci="kelipatan_tera_kg",
        nama="Kelipatan pembacaan tera",
        satuan="kg",
        arti="Angka di luar kelipatan ini diberi peringatan — tidak ditolak.",
        env="TIMBANGAN_KELIPATAN_TERA_KG",
        bawaan=lambda: tsettings.kelipatan_tera_kg,
        minimum=1, maksimum=100, desimal=2,
    ),
    Definisi(
        kunci="jam_kunci_otomatis",
        nama="Transaksi terkunci setelah",
        satuan="jam",
        arti="Setelah lewat, hanya Pengawas yang boleh mengoreksi.",
        env="TIMBANGAN_JAM_KUNCI",
        bawaan=lambda: tsettings.jam_kunci_otomatis,
        minimum=1, maksimum=720,
    ),
    Definisi(
        kunci="jam_tiket_menganggur",
        nama="Tiket ditandai lama setelah",
        satuan="jam",
        arti="Tiket terbuka yang menganggur lebih lama diberi tanda.",
        env="TIMBANGAN_JAM_TIKET_MENGANGGUR",
        bawaan=lambda: tsettings.jam_tiket_menganggur,
        minimum=1, maksimum=720,
    ),
    Definisi(
        kunci="maks_foto_mb",
        nama="Ukuran maksimum satu foto",
        satuan="MB",
        arti="Foto bukti disimpan di database agar tahan deploy ulang.",
        env="TIMBANGAN_MAKS_FOTO_MB",
        bawaan=lambda: tsettings.maks_foto_byte / (1024 * 1024),
        minimum=1, maksimum=20,
    ),
)

PETA: dict[str, Definisi] = {d.kunci: d for d in DAFTAR}


def _baca(teks: str) -> float:
    """Terima '20000', '20.000', dan '0,5' — sama seperti isian lain."""
    bersih = str(teks or "").strip().replace(" ", "")
    if not bersih:
        raise SetelanError("Nilai tidak boleh kosong.")
    if "," in bersih:
        bersih = bersih.replace(".", "").replace(",", ".")
    elif bersih.count(".") > 1:
        bersih = bersih.replace(".", "")
    elif bersih.count(".") == 1:
        depan, belakang = bersih.split(".")
        if len(belakang) == 3 and depan.lstrip("-+").lstrip("0") != "":
            bersih = bersih.replace(".", "")
    try:
        return float(bersih)
    except ValueError:
        raise SetelanError(f"'{teks}' bukan angka.") from None


async def semua(db: AsyncSession) -> dict[str, float]:
    """Nilai yang sedang berlaku untuk seluruh setelan."""
    tersimpan = {
        b.kunci: b.nilai
        for b in (await db.execute(select(TimbanganConfig))).scalars()
    }
    hasil: dict[str, float] = {}
    for d in DAFTAR:
        nilai = d.bawaan()
        if d.kunci in tersimpan:
            try:
                nilai = d.periksa(_baca(tersimpan[d.kunci]))
            except SetelanError:
                # Baris rusak tidak boleh menjatuhkan pos timbang — kembali ke
                # bawaan, dan biarkan halaman Pengaturan yang menampakkannya.
                nilai = d.bawaan()
        hasil[d.kunci] = nilai
    return hasil


async def asal(db: AsyncSession) -> dict[str, str]:
    """'data' bila disetel dari layar, 'environment' bila memakai bawaan."""
    tersimpan = set((await db.execute(select(TimbanganConfig.kunci))).scalars())
    return {
        d.kunci: ("data" if d.kunci in tersimpan else "environment")
        for d in DAFTAR
    }


async def muat_ke_permintaan(request, db: AsyncSession) -> dict[str, float]:
    """Sediakan setelan yang berlaku untuk seluruh halaman pada permintaan ini.

    Dipasang sebagai dependency router supaya template tidak perlu memanggil
    database sendiri — dan supaya teks bantuan di layar (mis. "kapasitas
    jembatan 20.000 kg") selalu menyebut angka yang benar-benar dipakai
    menolak input, bukan angka saat proses dinyalakan.

    Database yang sedang terganggu TIDAK boleh menjatuhkan halaman yang
    sebenarnya tidak membutuhkannya — halaman masuk, misalnya. Bila kueri
    gagal, kembali ke nilai bawaan; halaman yang memang perlu database akan
    tetap gagal pada kueri miliknya sendiri, dan itu memang seharusnya.
    """
    try:
        nilai = await semua(db)
    except Exception:
        nilai = {d.kunci: d.bawaan() for d in DAFTAR}
    request.state.setelan = nilai
    return nilai


async def simpan(
    db: AsyncSession, *, akun: TimbanganAkun, kunci: str, teks: str
) -> float:
    """Setel satu nilai. Mengembalikan nilai yang benar-benar tersimpan."""
    d = PETA.get(kunci)
    if d is None:
        raise SetelanError(f"Setelan '{kunci}' tidak dikenal.")

    nilai = d.periksa(_baca(teks))

    baris = (await db.execute(
        select(TimbanganConfig).where(TimbanganConfig.kunci == kunci)
    )).scalars().first()
    sebelum = baris.nilai if baris else f"{d.bawaan():g} (bawaan)"

    if baris is None:
        baris = TimbanganConfig(kunci=kunci, nilai=d.format(nilai))
        db.add(baris)
    else:
        baris.nilai = d.format(nilai)
    baris.diubah_oleh_id = akun.id

    from app.timbangan.service import catat_audit
    await catat_audit(
        db, akun=akun, aksi="UBAH_SETELAN", entitas="config", entitas_id=kunci,
        ringkasan=f"{d.nama}: {sebelum} → {d.format(nilai)} {d.satuan}",
        sebelum={kunci: sebelum}, sesudah={kunci: d.format(nilai)},
    )
    return nilai


async def kembalikan_bawaan(
    db: AsyncSession, *, akun: TimbanganAkun, kunci: str
) -> float:
    """Hapus baris setelan sehingga nilainya kembali mengikuti environment."""
    d = PETA.get(kunci)
    if d is None:
        raise SetelanError(f"Setelan '{kunci}' tidak dikenal.")

    baris = (await db.execute(
        select(TimbanganConfig).where(TimbanganConfig.kunci == kunci)
    )).scalars().first()
    if baris is not None:
        from app.timbangan.service import catat_audit
        await catat_audit(
            db, akun=akun, aksi="UBAH_SETELAN", entitas="config", entitas_id=kunci,
            ringkasan=f"{d.nama} dikembalikan ke bawaan {d.format(d.bawaan())} "
                      f"{d.satuan}",
            sebelum={kunci: baris.nilai}, sesudah={kunci: "(bawaan)"},
        )
        await db.delete(baris)
    return d.bawaan()
