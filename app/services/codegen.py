"""Generator kode transaksi berurutan per hari, mis. GB-YYYYMMDD-NN.

Prinsip dokumen: semua kode di-generate otomatis oleh sistem.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLot,
    InternalTransfer,
    MillingProcess,
    OutgoingRecord,
    PackagingPurchase,
    PkPurchaseBatch,
    PkRejection,
    PkTumpukanToSilo,
    PolishingProcess,
    PurchaseBatch,
)


async def _next_sequence(db: AsyncSession, prefix: str, count_stmt, tgl: date | None = None) -> str:
    """Bentuk kode PREFIX-YYYYMMDD-NN dari jumlah baris hari itu + 1."""
    tgl = tgl or date.today()
    used = (await db.execute(count_stmt)).scalar_one()
    seq = used + 1
    return f"{prefix}-{tgl:%Y%m%d}-{seq:02d}"


async def next_purchase_batch_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode batch pembelian gabah: GB-YYYYMMDD-NN (reset per hari).

    `tgl` untuk backdate: kode & urutan mengikuti tanggal kejadian.
    """
    tgl = tgl or date.today()
    stmt = (
        select(func.count())
        .select_from(PurchaseBatch)
        .where(PurchaseBatch.tanggal_pembelian == tgl)
    )
    return await _next_sequence(db, "GB", stmt, tgl)


async def next_drying_lot_code(db: AsyncSession) -> str:
    """Kode pengeringan: PGR-YYYYMMDD-NN (reset per hari).

    Dulu berawalan LOT-, dari masa ketika satu tabel dipaksa berarti dua hal:
    muatan yang dikeringkan bersama, DAN yang digiling bersama. Sejak silo
    boleh dicampur, keduanya berpisah — dan pemilik memutuskan "lot" dipakai
    HANYA untuk giling. Pengeringan punya namanya sendiri."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(DryingLot)
        .where(DryingLot.created_at >= start)
    )
    return await _next_sequence(db, "PGR", stmt)


async def next_milling_code(db: AsyncSession) -> str:
    """Kode lot giling: LOT-YYYYMMDD-NN (reset per hari).

    LOT- di sini, karena inilah lot yang sesungguhnya: terbentuk saat giling
    dimulai, dari seluruh isi silo. Dulu MIL-."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(MillingProcess)
        .where(MillingProcess.created_at >= start)
    )
    return await _next_sequence(db, "LOT", stmt)


async def next_transfer_code(db: AsyncSession) -> str:
    """Kode transfer internal: TRF-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(InternalTransfer)
        .where(InternalTransfer.created_at >= start)
    )
    return await _next_sequence(db, "TRF", stmt)


async def next_pk_purchase_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode beli PK luar (Gudang 2): PKB-YYYYMMDD-NN (reset per hari).

    `tgl` untuk backdate: kode & urutan mengikuti tanggal kejadian.
    """
    tgl = tgl or date.today()
    stmt = (
        select(func.count())
        .select_from(PkPurchaseBatch)
        .where(PkPurchaseBatch.tanggal_pembelian == tgl)
    )
    return await _next_sequence(db, "PKB", stmt, tgl)


async def next_rejection_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode PK ditolak & dikembalikan (Gudang 2): REJ-YYYYMMDD-NN (reset per hari)."""
    tgl = tgl or date.today()
    stmt = (
        select(func.count())
        .select_from(PkRejection)
        .where(PkRejection.tanggal == tgl)
    )
    return await _next_sequence(db, "REJ", stmt, tgl)


async def next_tumpukan_move_code(db: AsyncSession) -> str:
    """Kode pindah tumpukan→silo (Gudang 2): PTS-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(PkTumpukanToSilo)
        .where(PkTumpukanToSilo.created_at >= start)
    )
    return await _next_sequence(db, "PTS", stmt)


async def next_polishing_code(db: AsyncSession) -> str:
    """Kode proses penyosohan (Gudang 2): POL-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(PolishingProcess)
        .where(PolishingProcess.created_at >= start)
    )
    return await _next_sequence(db, "POL", stmt)


async def next_packaging_purchase_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode pembelian kemasan: PKP-YYYYMMDD-NN (reset per hari)."""
    tgl = tgl or date.today()
    stmt = (
        select(func.count())
        .select_from(PackagingPurchase)
        .where(PackagingPurchase.tanggal == tgl)
    )
    return await _next_sequence(db, "PKP", stmt, tgl)


async def next_outgoing_code(db: AsyncSession, tgl: date | None = None) -> str:
    """Kode barang keluar: OUT-YYYYMMDD-NN (reset per hari)."""
    tgl = tgl or date.today()
    stmt = (
        select(func.count())
        .select_from(OutgoingRecord)
        .where(OutgoingRecord.tanggal == tgl)
    )
    return await _next_sequence(db, "OUT", stmt, tgl)
