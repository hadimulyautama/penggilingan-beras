"""Menghentikan proses sementara — dan mencatat SEBABNYA.

Mesin berhenti di tengah jalan adalah kejadian sehari-hari. Sebelum ada
tempat untuk itu, operator hanya punya dua pilihan yang sama-sama merusak
catatan: membiarkan prosesnya "berjalan" padahal mesinnya mati, atau
menutupnya lalu memulai proses baru — yang membuat satu muatan gabah
terhitung dua kali.

Dua hal yang dijaga di sini:

  · **Jam berjalan dipisah dari jam tertahan.** Pengeringan 9 jam yang 4 jam
    di antaranya menunggu bahan bakar bukan pengeringan 9 jam. Menjumlahkan
    keduanya menyembunyikan satu-satunya angka yang bisa diperbaiki.

  · **Sebabnya wajib.** Yang ditanyakan saat hasil sehari sedikit selalu
    "kenapa", dan sebab yang tak dicatat akan dikarang berminggu-minggu
    kemudian. Daftarnya tak akan pernah lengkap, jadi ada jalan menulis
    sendiri — sebab yang berulang muncul di situ memang layak naik jadi
    pilihan tetap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import DryingLot, JedaProses, MillingProcess
from app.services.activity_log import log_activity


class JedaError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


#: Sebab BAWAAN. Yang dipakai layar & borang dibaca lewat
#: `app.services.setelan.sebab_jeda`, karena daftarnya memang bertambah di
#: lapangan — kotak "Lainnya, tulis sendiri" adalah katupnya, dan sebab yang
#: berulang muncul di situ layak naik jadi pilihan tetap.
#:
#: Urutannya: yang menghentikan MESIN lebih dulu, lalu
#: yang menghentikan PEKERJAAN. "Mesin giling rusak" dan "mesin pendukung
#: rusak" sengaja dipisah — sebab yang ambigu tak bisa dipakai menghitung
#: apa pun, dan "mesin rusak" saja jadi ambigu begitu ada mesin pendukung.
SEBAB = {
    "pengeringan": ("Listrik padam", "Mesin dryer rusak", "Mesin pendukung rusak",
                    "Bahan bakar habis", "Jam kerja habis"),
    "giling": ("Mesin giling rusak", "Mesin pendukung rusak",
               "Limbah produksi penuh", "Listrik padam", "Jam kerja habis"),
}
#: Katup untuk sebab yang belum ada di daftar. Daftar yang tak lengkap memaksa
#: orang memilih yang paling mirip — lalu angkanya berbohong dengan rapi.
SEBAB_LAIN = "Lainnya"


@dataclass
class JedaResult:
    jenis: str
    kode: str
    sebab: str
    #: Terisi hanya saat MELANJUTKAN: berapa lama ia tertahan barusan.
    tertahan_detik: float | None = None
    kali: int = 0


def _detik(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


async def _lot_berjalan(db: AsyncSession, kode: str) -> DryingLot:
    lot = (await db.execute(
        select(DryingLot).where(DryingLot.kode_lot == kode)
    )).scalars().first()
    if lot is None:
        raise JedaError(f"Pengeringan {kode} tidak ditemukan.")
    if lot.status != "proses":
        raise JedaError(f"Pengeringan {kode} sudah tidak berjalan.")
    return lot


async def _giling_berjalan(db: AsyncSession, kode: str) -> MillingProcess:
    proc = (await db.execute(
        select(MillingProcess).where(MillingProcess.kode_proses == kode)
    )).scalars().first()
    if proc is None:
        raise JedaError(f"Giling {kode} tidak ditemukan.")
    if proc.status != "proses":
        raise JedaError(f"Giling {kode} sudah ditutup.")
    return proc


def _saring(jenis: str):
    if jenis == "pengeringan":
        return JedaProses.jenis == "pengeringan"
    return JedaProses.jenis == "giling"


async def jeda_terbuka(db: AsyncSession, jenis: str, id_: int) -> JedaProses | None:
    """Jeda yang BELUM dilanjutkan untuk proses ini, bila ada."""
    kolom = (JedaProses.drying_lot_id if jenis == "pengeringan"
             else JedaProses.milling_process_id)
    return (await db.execute(
        select(JedaProses).where(kolom == id_, JedaProses.selesai.is_(None))
    )).scalars().first()


async def tertahan_detik(db: AsyncSession, jenis: str, id_: int,
                         sampai: datetime | None = None) -> float:
    """Total waktu tertahan proses ini — termasuk jeda yang masih berlangsung.

    Yang masih berlangsung ikut dihitung sampai SEKARANG; kalau tidak, proses
    yang sedang mati akan terlihat seolah jam tertahannya berhenti bertambah,
    dan itu justru saat angkanya paling perlu terlihat naik.
    """
    kolom = (JedaProses.drying_lot_id if jenis == "pengeringan"
             else JedaProses.milling_process_id)
    kini = sampai or now_local()
    baris = (await db.execute(select(JedaProses).where(kolom == id_))).scalars().all()
    return sum(_detik(j.mulai, j.selesai or kini) for j in baris)


async def hentikan(db: AsyncSession, *, user, jenis: str, kode: str,
                   sebab: str, sebab_lain: str | None = None) -> JedaResult:
    """Hentikan sementara. Prosesnya TIDAK ditutup — bahan & catatannya tetap."""
    jenis = (jenis or "").strip()
    if jenis not in SEBAB:
        raise JedaError("Sebutkan prosesnya: pengeringan atau giling.")
    sebab = (sebab or "").strip()
    if sebab == SEBAB_LAIN:
        sebab = (sebab_lain or "").strip()
        if not sebab:
            raise JedaError("Tulis sebabnya dulu — berhenti tanpa sebab tak bisa "
                            "dipakai memperbaiki apa pun.")
    if not sebab:
        raise JedaError("Pilih sebab berhentinya.")

    if jenis == "pengeringan":
        obj = await _lot_berjalan(db, kode)
        id_ = obj.id
    else:
        obj = await _giling_berjalan(db, kode)
        id_ = obj.id

    if await jeda_terbuka(db, jenis, id_) is not None:
        raise JedaError(f"{kode} memang sedang berhenti. Lanjutkan dulu.")

    now = now_local()
    db.add(JedaProses(
        jenis=jenis,
        drying_lot_id=id_ if jenis == "pengeringan" else None,
        milling_process_id=id_ if jenis == "giling" else None,
        sebab=sebab[:120], mulai=now, dicatat_oleh=user.id,
    ))
    await log_activity(
        db, table_name="jeda_proses", record_id=id_, action="INSERT",
        changed_by=user.id, new_value=f"{kode} berhenti — {sebab}",
    )
    await db.commit()
    kali = len((await db.execute(select(JedaProses).where(
        (JedaProses.drying_lot_id if jenis == "pengeringan"
         else JedaProses.milling_process_id) == id_))).scalars().all())
    return JedaResult(jenis=jenis, kode=kode, sebab=sebab, kali=kali)


async def lanjutkan(db: AsyncSession, *, user, jenis: str, kode: str) -> JedaResult:
    """Jalan lagi. Bisa nanti, bisa besok — prosesnya tak pernah ditutup."""
    if jenis not in SEBAB:
        raise JedaError("Sebutkan prosesnya: pengeringan atau giling.")
    if jenis == "pengeringan":
        obj = await _lot_berjalan(db, kode)
    else:
        obj = await _giling_berjalan(db, kode)

    jeda = await jeda_terbuka(db, jenis, obj.id)
    if jeda is None:
        raise JedaError(f"{kode} tidak sedang berhenti.")

    now = now_local()
    jeda.selesai = now
    lama = _detik(jeda.mulai, now)
    await log_activity(
        db, table_name="jeda_proses", record_id=obj.id, action="UPDATE",
        changed_by=user.id, field_name="selesai",
        new_value=f"{kode} lanjut — tertahan {lama / 3600:.1f} jam ({jeda.sebab})",
    )
    await db.commit()
    return JedaResult(jenis=jenis, kode=kode, sebab=jeda.sebab,
                      tertahan_detik=lama)


@dataclass
class Berhenti:
    sebab: str
    detik: float
    kali: int


async def rekap_berhenti(db: AsyncSession, *, sejak: datetime,
                         sampai: datetime | None = None) -> list[Berhenti]:
    """Jumlah waktu berhenti PER SEBAB, terbanyak lebih dulu.

    Dijumlah per sebab, bukan didaftar per kejadian: daftar kejadian cuma bisa
    dibaca, sedangkan yang dijumlah bisa dipakai memutuskan.
    """
    kini = sampai or now_local()
    baris = (await db.execute(
        select(JedaProses).where(JedaProses.mulai >= sejak)
    )).scalars().all()
    per: dict[str, Berhenti] = {}
    for j in baris:
        b = per.setdefault(j.sebab, Berhenti(sebab=j.sebab, detik=0.0, kali=0))
        b.detik += _detik(j.mulai, j.selesai or kini)
        b.kali += 1
    return sorted(per.values(), key=lambda b: b.detik, reverse=True)
