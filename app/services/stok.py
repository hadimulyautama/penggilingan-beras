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
    #: Berat gabah yang masuk — penyebut rendemen.
    bahan_kg: float = 0.0
    #: Berapa persen gabah keluar jadi PK. None bila bahannya tak diketahui.
    rendemen: float | None = None
    #: "basah" / "kering" / "campuran" — dari SELURUH batch sumbernya.
    #:
    #: Sengaja tidak memakai `pk_jenis`: ia membaca penunjuk TUNGGAL di
    #: `MillingProcess`, bentuk peninggalan masa ketika satu silo tak boleh
    #: dicampur. Begitu boleh, penunjuk itu menyebut salah satu sumber dan
    #: mendiamkan sisanya — dan lot campuran akan mengaku basah saja.
    kondisi: str | None = None
    #: Rincian bahan: (pemasok · kode batch, berat, kapan gabahnya masuk).
    #: Bentuknya sama dengan rincian di kartu-kartu lain, supaya mata membaca
    #: keduanya dengan cara yang sama.
    bahan: list[tuple[str, str, str]] = field(default_factory=list)
    tanggal: str | None = None
    #: Masih menyala mesinnya. PK-nya sudah ada, tapi angkanya belum final.
    berjalan: bool = False


def _tgl(d) -> str:
    return d.strftime("%d/%m") if d else "?"


def _kg(n) -> str:
    return f"{float(n or 0):,.0f} kg".replace(",", ".")


async def pk_gudang1(db: AsyncSession) -> list[LotPk]:
    """Tiap lot giling yang PK-nya masih tersisa di Gudang 1, terbaru dulu.

    Yang sudah habis terkirim tidak ditampilkan: stok adalah apa yang ADA, dan
    daftar yang memuat baris nol mengajari orang melewatkan barisnya.
    """
    from app.models import Supplier
    from app.penggilingan.gudang1.services.milling import (
        _pk_breakdown, hitung_rendemen, sumber_batch,
    )

    keluar: list[LotPk] = []
    for proc in (await db.execute(
        select(MillingProcess).order_by(MillingProcess.id.desc())
    )).scalars().all():
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia <= 0:
            continue
        # `sumber_batch` adalah SATU-SATUNYA jawaban "apa isi lot ini" — yang
        # sama dipakai HPP. Harga yang ikut dikembalikannya sengaja dibuang di
        # sini, bukan disaring di templat: layar ini dilihat operator juga.
        bahan, kondisi = [], set()
        for b, _harga, _lewat in await sumber_batch(db, proc):
            sup = await db.get(Supplier, b.supplier_id)
            nama = (sup.nama_supplier if sup else None) or "?"
            k = (b.kondisi_gabah or "").strip().lower()
            if k:
                kondisi.add(k)
            bahan.append((f"{nama} · {b.kode_batch}", _kg(b.berat_total_kg),
                          f"masuk {_tgl(b.tanggal_pembelian)}"
                          + (f" · {k}" if k else "")))
        keluar.append(LotPk(
            kode=proc.kode_proses,
            tersedia=bd.tersedia,
            dihasilkan=bd.produced,
            dikirim=bd.transferred,
            bahan_kg=float(proc.berat_gabah_masuk_kg or 0),
            # Penyebutnya dipinjam, bukan dipilih sendiri: dua layar yang
            # memakai penyebut berbeda akan menyebut rendemen berbeda untuk
            # lot yang sama.
            rendemen=hitung_rendemen(bd.produced, proc.berat_gabah_masuk_kg),
            kondisi=(kondisi.pop() if len(kondisi) == 1
                     else ("campuran" if kondisi else None)),
            bahan=bahan,
            tanggal=_tgl(proc.waktu_selesai or proc.waktu_mulai),
            berjalan=proc.status == "proses",
        ))
    return keluar
