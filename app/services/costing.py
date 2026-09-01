"""Biaya produksi PK & HPP penuh (bahan baku + operasional).

HPP penuh per kg PK = (biaya gabah + bongkar + pengeringan + operator +
tenaga milling + rubber roll + listrik) / output PK.
Tarif diatur di config (bisa via env).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    DryingLot,
    DryingLotBatch,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    PurchaseBatch,
    PurchaseBatchVerification,
)


@dataclass
class CostBreakdown:
    kode_proses: str
    kg_gabah: float
    pk_output: float
    dried: bool
    kondisi: str | None       # basah | kering | None
    bahan_baku: float | None  # None bila harga gabah belum terverifikasi
    bongkar: float
    pengeringan: float
    operator: float
    tenaga_milling: float
    rubber_roll: float
    listrik: float

    @property
    def operasional(self) -> float:
        return (
            self.bongkar + self.pengeringan + self.operator
            + self.tenaga_milling + self.rubber_roll + self.listrik
        )

    @property
    def total_penuh(self) -> float | None:
        if self.bahan_baku is None:
            return None
        return self.bahan_baku + self.operasional

    @property
    def hpp_penuh(self) -> float | None:
        t = self.total_penuh
        return t / self.pk_output if (t is not None and self.pk_output) else None


async def _pk_output(db: AsyncSession, proc: MillingProcess) -> float | None:
    v = (
        await db.execute(
            select(MillingProcessVerification.berat_output_final_kg).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    if v:
        return float(v)
    p = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc.id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalars().first()
    return float(p) if p else None


async def _sumber_info(db: AsyncSession, proc: MillingProcess):
    """(kg_gabah, dried, kondisi, bahan_baku|None) sumber sebuah proses."""
    if proc.drying_lot_id:
        lot = await db.get(DryingLot, proc.drying_lot_id)
        dried = lot is not None and lot.dryer_id is not None
        rows = (
            await db.execute(
                select(
                    PurchaseBatch.kondisi_gabah,
                    func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0),
                    func.count(PurchaseBatch.id),
                    func.count(PurchaseBatchVerification.id),
                    func.coalesce(
                        func.sum(PurchaseBatch.berat_total_kg * PurchaseBatchVerification.harga_per_kg),
                        0,
                    ),
                )
                .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .join(
                    PurchaseBatchVerification,
                    PurchaseBatchVerification.purchase_batch_id == PurchaseBatch.id,
                    isouter=True,
                )
                .where(DryingLotBatch.drying_lot_id == proc.drying_lot_id)
                .group_by(PurchaseBatch.kondisi_gabah)
            )
        ).all()
        kg = sum(float(r[1]) for r in rows)
        kondisi = rows[0][0] if rows else None
        n_batch = sum(int(r[2]) for r in rows)
        n_verif = sum(int(r[3]) for r in rows)
        bahan = sum(float(r[4]) for r in rows) if n_verif == n_batch and n_batch else None
        return kg, dried, kondisi, bahan
    if proc.purchase_batch_id:
        b = await db.get(PurchaseBatch, proc.purchase_batch_id)
        if b is None:
            return 0.0, False, None, None
        v = (
            await db.execute(
                select(PurchaseBatchVerification.harga_per_kg).where(
                    PurchaseBatchVerification.purchase_batch_id == b.id
                )
            )
        ).scalars().first()
        # Batch "menunggu bobot" (belum ada bobot dari timbang) → belum bisa dihitung HPP.
        if b.berat_total_kg is None:
            return 0.0, False, b.kondisi_gabah, None
        berat = float(b.berat_total_kg)
        bahan = berat * float(v) if v else None
        # Milling langsung dari batch (tanpa lot pengeringan) = tak dikeringkan.
        return berat, False, b.kondisi_gabah, bahan
    return float(proc.berat_gabah_masuk_kg or 0), False, None, None


async def production_cost(db: AsyncSession, proc: MillingProcess) -> CostBreakdown | None:
    """Rincian biaya produksi sebuah proses. None bila output PK belum ada."""
    pk = await _pk_output(db, proc)
    if not pk:
        return None
    kg, dried, kondisi, bahan = await _sumber_info(db, proc)
    if not kg:
        kg = float(proc.berat_gabah_masuk_kg or 0)

    # Gabah basah PASTI dikeringkan (tak bisa langsung silo/giling). Gabah
    # kering: dikeringkan hanya bila lewat dryer (else langsung silo = gratis).
    if kondisi == "basah":
        dried = True
        pengeringan_rate = settings.biaya_pengeringan_basah_per_kg
    elif kondisi == "kering" and dried:
        pengeringan_rate = settings.biaya_pengeringan_kering_per_kg
    else:
        pengeringan_rate = 0.0

    rubber_per_kg = (
        settings.rubber_roll_harga_per_set / (settings.rubber_roll_umur_ton * 1000)
        if settings.rubber_roll_umur_ton else 0.0
    )
    return CostBreakdown(
        kode_proses=proc.kode_proses,
        kg_gabah=kg, pk_output=pk, dried=dried, kondisi=kondisi, bahan_baku=bahan,
        bongkar=settings.biaya_bongkar_per_kg_gabah * kg,
        pengeringan=pengeringan_rate * kg,
        operator=settings.biaya_operator_per_proses,  # FLAT per proses milling
        tenaga_milling=settings.biaya_tenaga_milling_per_kg_pk * pk,
        rubber_roll=rubber_per_kg * kg,
        listrik=settings.biaya_listrik_milling_per_kg_gabah * kg,
    )
