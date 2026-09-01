"""Logika bisnis verifikasi harga gabah oleh staff/admin."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    Notification,
    PurchaseBatch,
    PurchaseBatchVerification,
    Supplier,
    User,
)
from app.services.activity_log import log_activity


class BatchNotFound(Exception):
    """Kode batch tidak ditemukan."""


def compute_price(
    berat_kg: float, metode: str, nilai_rupiah: float
) -> tuple[float, float]:
    """Hitung (total_biaya, harga_per_kg) dari salah satu metode input.

    metode 'total'  -> nilai adalah total biaya.
    metode 'per_kg' -> nilai adalah harga per kg.
    """
    if metode == "total":
        total = float(nilai_rupiah)
        per_kg = total / berat_kg if berat_kg else 0.0
    else:  # per_kg
        per_kg = float(nilai_rupiah)
        total = per_kg * berat_kg
    return total, per_kg


async def get_batch_by_kode(db: AsyncSession, kode: str) -> PurchaseBatch | None:
    stmt = select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode)
    return (await db.execute(stmt)).scalars().first()


@dataclass
class VerificationResult:
    batch: PurchaseBatch
    supplier_nama: str
    total_biaya: float
    harga_per_kg: float
    re_verified: bool  # True jika batch sebelumnya sudah pernah diverifikasi


async def verify_gabah_price(
    db: AsyncSession,
    *,
    user: User,
    batch: PurchaseBatch,
    metode: str,
    nilai_rupiah: float,
) -> VerificationResult:
    """Simpan/replace verifikasi harga, hapus flag unverified, catat audit."""
    berat = float(batch.berat_total_kg or 0)
    total, per_kg = compute_price(berat, metode, nilai_rupiah)

    # Upsert purchase_batch_verifications (unik per batch).
    stmt = select(PurchaseBatchVerification).where(
        PurchaseBatchVerification.purchase_batch_id == batch.id
    )
    verif = (await db.execute(stmt)).scalars().first()
    re_verified = verif is not None

    now = now_local()
    if verif is None:
        verif = PurchaseBatchVerification(purchase_batch_id=batch.id)
        db.add(verif)
    verif.harga_per_kg = per_kg
    verif.total_biaya = total
    verif.metode_harga = metode
    verif.verified_by = user.id
    verif.waktu_verifikasi = now
    verif.status_verifikasi = "terverifikasi"

    batch.flag_unverified = False

    await log_activity(
        db,
        table_name="purchase_batch_verifications",
        record_id=batch.id,
        action="UPDATE" if re_verified else "INSERT",
        changed_by=user.id,
        field_name="harga",
        new_value=f"total={total:.0f} | per_kg={per_kg:.2f} | metode={metode}",
    )

    # Tutup notifikasi verifikasi yang masih terbuka untuk batch ini.
    await db.execute(
        update(Notification)
        .where(
            Notification.tipe == "verifikasi_harga_gabah",
            Notification.table_name == "purchase_batches",
            Notification.record_id == batch.id,
            Notification.status != "selesai",
        )
        .values(status="selesai")
    )

    supplier = await db.get(Supplier, batch.supplier_id)
    await db.commit()
    await db.refresh(batch)
    return VerificationResult(
        batch=batch,
        supplier_nama=supplier.nama_supplier if supplier else "-",
        total_biaya=total,
        harga_per_kg=per_kg,
        re_verified=re_verified,
    )
