"""Logika bisnis transfer internal Gudang 1 -> Gudang 2 + HPP snapshot PK."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLotBatch,
    InternalTransfer,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    PurchaseBatch,
    PurchaseBatchVerification,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_transfer_code

_LOKASI = {"silo_a": "Silo A", "silo_b": "Silo B", "ditumpuk": "tumpukan"}


class TransferError(Exception):
    """Kesalahan transfer dengan pesan siap-tampil (args[0])."""


async def _gabah_cost(db: AsyncSession, proc: MillingProcess) -> float | None:
    """Total biaya gabah sumber milling. None bila ada yang belum diverifikasi."""
    if proc.drying_lot_id:
        # Semua batch dalam lot harus terverifikasi.
        unver = (
            await db.execute(
                select(func.count())
                .select_from(DryingLotBatch)
                .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
                .where(
                    DryingLotBatch.drying_lot_id == proc.drying_lot_id,
                    PurchaseBatch.flag_unverified.is_(True),
                )
            )
        ).scalar_one()
        if unver:
            return None
        total = (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            PurchaseBatch.berat_total_kg
                            * PurchaseBatchVerification.harga_per_kg
                        ),
                        0,
                    )
                )
                .select_from(DryingLotBatch)
                .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
                .join(
                    PurchaseBatchVerification,
                    PurchaseBatchVerification.purchase_batch_id == PurchaseBatch.id,
                )
                .where(DryingLotBatch.drying_lot_id == proc.drying_lot_id)
            )
        ).scalar_one()
        return float(total)
    if proc.purchase_batch_id:
        b = await db.get(PurchaseBatch, proc.purchase_batch_id)
        if b is None or b.flag_unverified:
            return None
        v = (
            await db.execute(
                select(PurchaseBatchVerification).where(
                    PurchaseBatchVerification.purchase_batch_id == b.id
                )
            )
        ).scalars().first()
        if v is None or v.harga_per_kg is None:
            return None
        return float(b.berat_total_kg) * float(v.harga_per_kg)
    return None


async def hpp_per_kg_pk(db: AsyncSession, proc: MillingProcess) -> float | None:
    """HPP per kg PK = biaya gabah / output PK terverifikasi. None bila belum lengkap."""
    verif = (
        await db.execute(
            select(MillingProcessVerification).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    if verif is None or not verif.berat_output_final_kg:
        return None
    cost = await _gabah_cost(db, proc)
    if cost is None:
        return None
    output = float(verif.berat_output_final_kg)
    return cost / output if output else None


async def _produced_pk(db: AsyncSession, proc_id: int) -> float:
    v = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc_id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalars().first()
    return float(v) if v is not None else 0.0


async def _transferred_pk(db: AsyncSession, proc_id: int) -> float:
    r = (
        await db.execute(
            select(func.coalesce(func.sum(InternalTransfer.berat_kg), 0)).where(
                InternalTransfer.milling_process_id == proc_id,
                InternalTransfer.status == "terkirim",
            )
        )
    ).scalar_one()
    return float(r)


async def pending_transfer_kg(db: AsyncSession, proc_id: int) -> float:
    """PK siap kirim (stok) sebuah proses = hasil produksi − yang sudah dikirim."""
    return max(await _produced_pk(db, proc_id) - await _transferred_pk(db, proc_id), 0.0)


@dataclass
class TransferResult:
    transfer: InternalTransfer
    kode_proses: str
    lokasi_label: str
    hpp_per_kg: float | None


async def create_internal_transfer(
    db: AsyncSession, *, user, kode_proses: str, lokasi_tujuan: str,
    berat: float | None = None,
) -> TransferResult:
    """Kirim PK dari sebuah milling ke Gudang 2. Mengurangi stok siap kirim.

    `berat` opsional: bila tidak disebut, kirim SEMUA stok yang tersedia.
    """
    if lokasi_tujuan not in _LOKASI:
        raise TransferError("Tujuan harus: Silo A, Silo B, atau ditumpuk.")
    proc = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode_proses)
        )
    ).scalars().first()
    if proc is None:
        raise TransferError(f"Proses {kode_proses} tidak ditemukan.")

    tersedia = await pending_transfer_kg(db, proc.id)
    if tersedia <= 0:
        raise TransferError(
            f"Tidak ada stok PK dari {kode_proses} untuk dikirim "
            "(hasil giling belum dicatat, atau semua sudah terkirim)."
        )
    kirim = tersedia if berat is None else min(float(berat), tersedia)

    hpp = await hpp_per_kg_pk(db, proc)
    now = now_local()
    transfer = InternalTransfer(
        kode_transfer=await next_transfer_code(db),
        milling_process_id=proc.id,
        drying_lot_id=proc.drying_lot_id,
        berat_kg=kirim,
        lokasi_tujuan=lokasi_tujuan,
        hpp_per_kg=hpp,
        waktu=now,
        created_by=user.id,
        status="terkirim",
    )
    db.add(transfer)
    await db.flush()
    await log_activity(
        db, table_name="internal_transfers", record_id=transfer.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{transfer.kode_transfer} | {kirim:.0f}kg -> {_LOKASI[lokasi_tujuan]} | hpp={hpp}",
    )
    await db.commit()
    await db.refresh(transfer)
    return TransferResult(
        transfer=transfer, kode_proses=kode_proses,
        lokasi_label=_LOKASI[lokasi_tujuan], hpp_per_kg=hpp,
    )


# ─────────────────────────── Laporan ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_pk_siap_transfer(db: AsyncSession) -> str:
    """PK siap kirim ke Gudang 2 = hasil − yang sudah dikirim, per proses."""
    procs = (
        await db.execute(select(MillingProcess).order_by(MillingProcess.kode_proses))
    ).scalars().all()
    items: list[tuple[str, float]] = []
    for p in procs:
        avail = await pending_transfer_kg(db, p.id)
        if avail > 0:
            items.append((p.kode_proses, avail))
    if not items:
        return "🚚 Tidak ada PK siap kirim ke Gudang 2."
    total = sum(a for _, a in items)
    lines = [f"🚚 PK siap kirim ke Gudang 2: {_kg(total)}"]
    for kode, a in items:
        lines.append(f"• dari {kode}: {_kg(a)}")
    return "\n".join(lines)


async def laporan_transfer(db: AsyncSession) -> str:
    """Riwayat transfer internal (terbaru dulu)."""
    rows = (
        await db.execute(
            select(InternalTransfer, MillingProcess.kode_proses)
            .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
            .order_by(InternalTransfer.id.desc())
            .limit(10)
        )
    ).all()
    if not rows:
        return "🚚 Belum ada transfer ke Gudang 2."
    lines = ["🚚 Transfer terakhir ke Gudang 2:"]
    for t, kode in rows:
        hpp = f" · HPP {_rp(float(t.hpp_per_kg))}/kg" if t.hpp_per_kg is not None else ""
        lines.append(
            f"• {t.kode_transfer}: {_kg(float(t.berat_kg))} dari {kode} "
            f"→ {_LOKASI.get(t.lokasi_tujuan, t.lokasi_tujuan)}{hpp}"
        )
    return "\n".join(lines)
