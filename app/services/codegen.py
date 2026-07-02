"""Generator kode transaksi berurutan per hari, mis. GB-YYYYMMDD-NN.

Prinsip dokumen: semua kode di-generate otomatis oleh sistem.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import DryingLot, MillingProcess, PurchaseBatch


async def _next_sequence(db: AsyncSession, prefix: str, count_stmt) -> str:
    """Bentuk kode PREFIX-YYYYMMDD-NN dari jumlah baris hari ini + 1."""
    today = date.today()
    used = (await db.execute(count_stmt)).scalar_one()
    seq = used + 1
    return f"{prefix}-{today:%Y%m%d}-{seq:02d}"


async def next_purchase_batch_code(db: AsyncSession) -> str:
    """Kode batch pembelian gabah: GB-YYYYMMDD-NN (reset per hari)."""
    today = date.today()
    stmt = (
        select(func.count())
        .select_from(PurchaseBatch)
        .where(PurchaseBatch.tanggal_pembelian == today)
    )
    return await _next_sequence(db, "GB", stmt)


async def next_drying_lot_code(db: AsyncSession) -> str:
    """Kode lot pengeringan: LOT-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(DryingLot)
        .where(DryingLot.created_at >= start)
    )
    return await _next_sequence(db, "LOT", stmt)


async def next_milling_code(db: AsyncSession) -> str:
    """Kode proses milling: MIL-YYYYMMDD-NN (reset per hari)."""
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count())
        .select_from(MillingProcess)
        .where(MillingProcess.created_at >= start)
    )
    return await _next_sequence(db, "MIL", stmt)
