"""Stok PK Gudang 1 — hasil giling yang masih ada, dirinci per lot.

Satu angka gabungan menjawab "berapa" tetapi tidak menjawab "yang mana", dan
di gudang pertanyaan kedua yang lebih sering muncul: PK mana yang sudah lama
menumpuk, PK mana yang gabahnya dari pemasok yang sedang dipersoalkan. Maka
barisnya adalah LOT GILING — satuan yang sama dengan yang tertulis di kartu
dan di catatan, jadi orang tak perlu menerjemahkan apa pun.

Gudang 2 (beras putih, menir, bekatul) sengaja belum ikut: pemilik memutuskan
Gudang 1 dulu. Kodenya tidak ditinggalkan menganggur di sini — riwayat git
menyimpannya, dan kode menganggur yang menunggu dipakai lagi selalu sudah
basi saat gilirannya tiba.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MillingProcess


@dataclass
class LotPk:
    """Sisa PK satu lot giling, beserta asal gabahnya."""

    kode: str
    #: Yang masih ada di Gudang 1 = dihasilkan − dikirim − dijual langsung.
    tersedia: float
    dihasilkan: float
    dikirim: float
    #: Nama pemasok gabahnya — dari SELURUH isi lot, bukan sumber pertamanya.
    pemasok: list[str] = field(default_factory=list)
    tanggal: str | None = None
    #: Masih menyala mesinnya. PK-nya sudah ada, tapi angkanya belum final.
    berjalan: bool = False


def _tgl(d) -> str:
    return d.strftime("%d/%m") if d else "?"


def _pemasok_ringkas(nama: list[str]) -> str:
    """Dua disebut, sisanya dihitung — baris keterangan tak boleh lebih panjang
    daripada barisnya sendiri."""
    if not nama:
        return ""
    if len(nama) <= 2:
        return " & ".join(nama)
    return f"{nama[0]}, {nama[1]} +{len(nama) - 2} lagi"


async def pk_gudang1(db: AsyncSession) -> list[LotPk]:
    """Tiap lot giling yang PK-nya masih tersisa di Gudang 1, terbaru dulu.

    Yang sudah habis terkirim tidak ditampilkan: stok adalah apa yang ADA, dan
    daftar yang memuat baris nol mengajari orang melewatkan barisnya.
    """
    from app.penggilingan.gudang1.services.milling import (
        _milling_supplier_names, _pk_breakdown,
    )

    keluar: list[LotPk] = []
    for proc in (await db.execute(
        select(MillingProcess).order_by(MillingProcess.id.desc())
    )).scalars().all():
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia <= 0:
            continue
        keluar.append(LotPk(
            kode=proc.kode_proses,
            tersedia=bd.tersedia,
            dihasilkan=bd.produced,
            dikirim=bd.transferred,
            pemasok=await _milling_supplier_names(db, proc),
            tanggal=_tgl(proc.waktu_selesai or proc.waktu_mulai),
            berjalan=proc.status == "proses",
        ))
    return keluar
