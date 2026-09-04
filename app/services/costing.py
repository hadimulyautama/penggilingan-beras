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
    """(kg_gabah, dried, kondisi, bahan_baku|None, biaya_pengeringan) sumber proses.

    Isinya dibaca dari `milling.sumber_batch` — satu tempat untuk pertanyaan
    "apa isi proses ini", dipakai HPP maupun analitik.

    Biaya pengeringan dijumlahkan PER BATCH, bukan satu tarif dikali total.
    Satu silo bisa berisi gabah yang lewat dryer dan gabah kering yang langsung
    masuk; menagihkan satu tarif untuk keduanya salah ke dua arah sekaligus —
    yang kering ikut membayar pengeringan yang tak pernah terjadi, dan
    rata-ratanya menyembunyikan keduanya.
    """
    from app.penggilingan.gudang1.services.milling import sumber_batch

    sumber = await sumber_batch(db, proc)
    if not sumber:
        return float(proc.berat_gabah_masuk_kg or 0), False, None, None, 0.0

    kg = 0.0
    bahan = 0.0
    semua_berharga = True
    pengeringan = 0.0
    kondisi_ada: set[str] = set()
    dried = False

    for b, harga, lewat_dryer in sumber:
        # Batch "menunggu bobot" (belum ada bobot dari timbang) tak bisa
        # dihitung — ia diabaikan di sini, dan rekonsiliasi yang menagihnya.
        if b.berat_total_kg is None:
            semua_berharga = False
            continue
        berat = float(b.berat_total_kg)
        kg += berat
        if b.kondisi_gabah:
            kondisi_ada.add(b.kondisi_gabah)
        if harga is None:
            semua_berharga = False
        else:
            bahan += berat * harga

        # Gabah basah PASTI dikeringkan — ia tak bisa langsung ke silo.
        # Gabah kering hanya dikenai biaya bila memang lewat dryer.
        if b.kondisi_gabah == "basah":
            dried = True
            pengeringan += settings.biaya_pengeringan_basah_per_kg * berat
        elif lewat_dryer:
            dried = True
            pengeringan += settings.biaya_pengeringan_kering_per_kg * berat

    kondisi = (kondisi_ada.pop() if len(kondisi_ada) == 1
               else ("campuran" if kondisi_ada else None))
    return kg, dried, kondisi, (bahan if semua_berharga and kg else None), pengeringan


async def production_cost(db: AsyncSession, proc: MillingProcess) -> CostBreakdown | None:
    """Rincian biaya produksi sebuah proses. None bila output PK belum ada."""
    pk = await _pk_output(db, proc)
    if not pk:
        return None
    kg, dried, kondisi, bahan, pengeringan = await _sumber_info(db, proc)
    if not kg:
        kg = float(proc.berat_gabah_masuk_kg or 0)

    rubber_per_kg = (
        settings.rubber_roll_harga_per_set / (settings.rubber_roll_umur_ton * 1000)
        if settings.rubber_roll_umur_ton else 0.0
    )
    return CostBreakdown(
        kode_proses=proc.kode_proses,
        kg_gabah=kg, pk_output=pk, dried=dried, kondisi=kondisi, bahan_baku=bahan,
        bongkar=settings.biaya_bongkar_per_kg_gabah * kg,
        pengeringan=pengeringan,
        operator=settings.biaya_operator_per_proses,  # FLAT per proses milling
        tenaga_milling=settings.biaya_tenaga_milling_per_kg_pk * pk,
        rubber_roll=rubber_per_kg * kg,
        listrik=settings.biaya_listrik_milling_per_kg_gabah * kg,
    )
