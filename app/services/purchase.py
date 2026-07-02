"""Logika bisnis pembelian gabah (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import now_local
from app.models import PurchaseBatch, Supplier, User
from app.services.activity_log import log_activity
from app.services.codegen import next_purchase_batch_code
from app.services.notification import create_notification


class DailyLimitReached(Exception):
    """Batas maksimal batch pembelian gabah per hari terlampaui."""


async def find_or_create_supplier(db: AsyncSession, nama: str) -> tuple[Supplier, bool]:
    """Cari supplier aktif (case-insensitive). Kembalikan (supplier, dibuat_baru)."""
    nama = nama.strip()
    stmt = select(Supplier).where(
        func.lower(Supplier.nama_supplier) == nama.lower(),
        Supplier.deleted_at.is_(None),
    )
    supplier = (await db.execute(stmt)).scalars().first()
    if supplier:
        return supplier, False
    supplier = Supplier(nama_supplier=nama, status="aktif")
    db.add(supplier)
    await db.flush()
    return supplier, True


async def count_batches_today(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(PurchaseBatch)
        .where(PurchaseBatch.tanggal_pembelian == date.today())
    )
    return (await db.execute(stmt)).scalar_one()


@dataclass
class CreatedBatch:
    batch: PurchaseBatch
    supplier: Supplier
    supplier_created: bool


async def create_purchase_batch(
    db: AsyncSession,
    *,
    user: User,
    nama_supplier: str,
    berat_kg: float,
    kondisi_gabah: str,
    no_polisi_truk: str | None,
    kadar_air_awal_persen: float | None,
) -> CreatedBatch:
    """Buat batch pembelian gabah + audit + notifikasi verifikasi harga.

    Melempar DailyLimitReached jika sudah mencapai batas harian.
    """
    if await count_batches_today(db) >= settings.max_purchase_batch_per_day:
        raise DailyLimitReached(settings.max_purchase_batch_per_day)

    supplier, created = await find_or_create_supplier(db, nama_supplier)

    kode = await next_purchase_batch_code(db)
    now = now_local()
    batch = PurchaseBatch(
        kode_batch=kode,
        supplier_id=supplier.id,
        berat_total_kg=berat_kg,
        no_polisi_truk=no_polisi_truk,
        kondisi_gabah=kondisi_gabah,
        kadar_air_awal_persen=kadar_air_awal_persen,
        tanggal_pembelian=now.date(),
        waktu_pembelian=now,
        input_by=user.id,
        status_batch="baru",
        flag_unverified=True,
    )
    db.add(batch)
    await db.flush()

    await log_activity(
        db,
        table_name="purchase_batches",
        record_id=batch.id,
        action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {berat_kg:.0f}kg | {kondisi_gabah}",
    )
    await create_notification(
        db,
        tipe="verifikasi_harga_gabah",
        pesan=(
            f"🟡 Batch {kode} ({supplier.nama_supplier}, {berat_kg:.0f} kg) "
            f"menunggu verifikasi harga."
        ),
        target_role="staff",
        prioritas="kuning",
        table_name="purchase_batches",
        record_id=batch.id,
    )

    await db.commit()
    await db.refresh(batch)
    return CreatedBatch(batch=batch, supplier=supplier, supplier_created=created)


async def undo_purchase_batch(db: AsyncSession, *, batch_id: int, user: User) -> bool:
    """Batalkan batch dalam jendela waktu (default 15 menit) bila belum diproses.

    Kembalikan True jika berhasil dibatalkan.
    """
    batch = await db.get(PurchaseBatch, batch_id)
    if batch is None:
        return False

    window = timedelta(minutes=settings.undo_window_minutes)
    if now_local() - batch.waktu_pembelian > window:
        return False
    if batch.status_batch != "baru":
        return False  # sudah ada transaksi lanjutan (mis. masuk lot/silo)

    await log_activity(
        db,
        table_name="purchase_batches",
        record_id=batch.id,
        action="DELETE",
        changed_by=user.id,
        old_value=batch.kode_batch,
        alasan="Dibatalkan operator dalam jendela undo",
    )
    await db.delete(batch)
    await db.commit()
    return True
