"""Pekerjaan yang belum tertutup — isi layar "Berjalan".

Dibagi dua, dan pembagian itulah inti layar ini:

  · **Menunggu Anda** — ada orang yang harus bertindak SEKARANG. Inilah yang
    dihitung lencana di bilah navigasi;
  · **Sedang berjalan** — menunggu WAKTU, bukan orang: gabah yang sedang
    dikeringkan, giling yang sedang berputar. Tidak dihitung.

Kalau keduanya dijadikan satu angka, lencananya tidak pernah nol — dan lencana
yang tidak pernah nol mengajari orang mengabaikan lencana.

Tiap baris membawa `aksi`: id aksi yang MENUTUPnya. Layar memakainya untuk
membuka lembar aksi yang benar dalam satu ketukan. Itu bedanya dengan laporan
status gudang — laporan memberi tahu, layar ini menyelesaikan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLot,
    MillingProcess,
    MillingProcessVerification,
    MillingQcLog,
    PurchaseBatch,
    SiloStorage,
    Supplier,
    User,
)


@dataclass
class Baris:
    kode: str
    isi: str
    keadaan: str
    #: Aksi yang menutup baris ini. None = tidak ada yang bisa dikerjakan
    #: sekarang; barisnya tampil tanpa panah dan tidak bisa ditekan.
    aksi: str | None = None
    sejak: datetime | None = None


@dataclass
class Berjalan:
    menunggu: list[Baris] = field(default_factory=list)
    berjalan: list[Baris] = field(default_factory=list)

    @property
    def jumlah_menunggu(self) -> int:
        return len(self.menunggu)


def _lama(sejak: datetime | None) -> str:
    """Sudah berapa lama — dalam kata, bukan cap waktu.

    "2 jam 40 menit" memberi tahu apakah sesuatu tertinggal; "08:12" menuntut
    pembacanya menghitung sendiri sambil berdiri di gudang.
    """
    if sejak is None:
        return ""
    detik = (now_local() - sejak).total_seconds()
    if detik < 0:
        return ""
    jam, menit = int(detik // 3600), int((detik % 3600) // 60)
    if jam >= 24:
        hari = jam // 24
        return f"{hari} hari {jam % 24} jam"
    if jam:
        return f"{jam} jam {menit} menit"
    return f"{menit} menit"


def _kg(n) -> str:
    return f"{float(n or 0):,.0f} kg".replace(",", ".")


async def _tiket_belum_ditaut(db: AsyncSession) -> list[Baris]:
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    baris = []
    for t in await tiket_masuk_aktif(db):
        if not str(t.get("jenis_kode", "")).startswith("GABAH"):
            continue                      # PK punya alurnya sendiri
        nama = t.get("nama_supplier") or t.get("pihak_nama") or "?"
        bobot = t.get("berat_hpp_kg")
        isi = f"{nama} · {t.get('nomor_polisi') or '-'}"
        if bobot:
            isi += f" · {_kg(bobot)}"
        baris.append(Baris(
            kode=t["kode"], isi=isi, aksi="gabah_masuk",
            keadaan=("tiket sudah ditutup — susulan" if t.get("susulan")
                     else "belum ditaut ke batch"),
        ))
    return baris


async def _lot(db: AsyncSession, *, pendinginan_selesai: bool) -> list[DryingLot]:
    belum_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
    syarat = (DryingLot.waktu_selesai_pendinginan.is_not(None)
              if pendinginan_selesai else DryingLot.waktu_selesai_pendinginan.is_(None))
    return list((await db.execute(
        select(DryingLot).where(
            DryingLot.status == "selesai",
            DryingLot.dryer_id.is_not(None),
            syarat, belum_silo,
        ).order_by(DryingLot.id.desc())
    )).scalars().all())


async def untuk_gudang1(db: AsyncSession) -> Berjalan:
    """Pekerjaan operator Gudang 1, dari truk masuk sampai giling ditutup."""
    b = Berjalan()

    b.menunggu += await _tiket_belum_ditaut(db)

    for lot in await _lot(db, pendinginan_selesai=True):
        b.menunggu.append(Baris(
            kode=lot.kode_lot, isi="sudah dingin, dryer perlu dikosongkan",
            keadaan="siap dipindah ke silo", aksi="pindah_silo",
            sejak=lot.waktu_selesai_pendinginan,
        ))

    for lot in await _lot(db, pendinginan_selesai=False):
        b.menunggu.append(Baris(
            kode=lot.kode_lot, isi="pengeringan selesai, sedang didinginkan",
            keadaan="nyatakan pendinginan selesai", aksi="selesai_pendinginan",
            sejak=lot.waktu_selesai_pengeringan,
        ))

    # Giling yang sudah ditutup tetapi belum di-QC / belum diverifikasi TIDAK
    # masuk sini: itu pekerjaan staff, bukan operator. Lihat `untuk_staff`.
    for lot in (await db.execute(
        select(DryingLot).where(DryingLot.status == "proses")
        .order_by(DryingLot.id.desc())
    )).scalars().all():
        b.berjalan.append(Baris(
            kode=lot.kode_lot, isi="sedang dikeringkan",
            keadaan="menunggu kadar air turun", aksi="kadar_air",
            sejak=lot.waktu_mulai_pengeringan,
        ))

    for p in (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
        .order_by(MillingProcess.id.desc())
    )).scalars().all():
        b.berjalan.append(Baris(
            kode=p.kode_proses, isi=f"digiling · {_kg(p.berat_gabah_masuk_kg)} gabah masuk",
            keadaan="catat hasil, tutup bila selesai", aksi="hasil_giling",
            sejak=p.waktu_mulai,
        ))
    return b


async def untuk_staff(db: AsyncSession) -> Berjalan:
    """Yang tertahan menunggu keputusan staff/Direksi — bukan pekerjaan fisik."""
    b = Berjalan()

    for batch, nama in (await db.execute(
        select(PurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
        .where(PurchaseBatch.flag_unverified.is_(True))
        .order_by(PurchaseBatch.id.desc())
    )).all():
        b.menunggu.append(Baris(
            kode=batch.kode_batch, isi=f"{nama} · {_kg(batch.berat_total_kg)}",
            keadaan="harga belum diverifikasi", aksi="verify_gabah",
            sejak=batch.created_at,
        ))

    selesai = (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "selesai")
        .order_by(MillingProcess.id.desc())
    )).scalars().all()
    for p in selesai:
        ada_qc = (await db.execute(
            select(func.count()).select_from(MillingQcLog)
            .where(MillingQcLog.milling_process_id == p.id)
        )).scalar_one()
        if not ada_qc:
            b.menunggu.append(Baris(
                kode=p.kode_proses, isi="giling selesai, mutu belum diperiksa",
                keadaan="menunggu QC", aksi="qc_giling", sejak=p.waktu_selesai))
        ada_v = (await db.execute(
            select(MillingProcessVerification.id)
            .where(MillingProcessVerification.milling_process_id == p.id)
        )).scalars().first()
        if not ada_v:
            b.menunggu.append(Baris(
                kode=p.kode_proses, isi="output giling belum diverifikasi",
                keadaan="menunggu verifikasi output", aksi="verify_output",
                sejak=p.waktu_selesai))
    return b


async def untuk(db: AsyncSession, user: User) -> Berjalan:
    """Gabungkan sesuai peran — server yang memutuskan, bukan layar."""
    from app.bots.common import can_see_financials

    from app.web.miniapp import _is_g1_operator, _is_g2_operator

    b = Berjalan()
    if await _is_g1_operator(user):
        g = await untuk_gudang1(db)
        b.menunggu += g.menunggu
        b.berjalan += g.berjalan
    if can_see_financials(user):
        s = await untuk_staff(db)
        b.menunggu += s.menunggu
        b.berjalan += s.berjalan
        # Staff & Direksi tak terikat satu gudang; keadaan fisik G1 tetap
        # perlu terlihat, tetapi sebagai kabar — bukan sebagai tugas mereka.
        if not await _is_g1_operator(user):
            b.berjalan += (await untuk_gudang1(db)).berjalan
    if await _is_g2_operator(user):
        pass    # Gudang 2 menyusul — lihat catatan di docs/RANCANGAN.md §11.
    return b
