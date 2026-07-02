"""Logika bisnis transfer internal Gudang 1 -> Gudang 2 + HPP snapshot PK."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLotBatch,
    InternalTransfer,
    MillingPkRouting,
    MillingProcess,
    MillingProcessVerification,
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


async def pending_transfer_kg(db: AsyncSession, proc_id: int) -> float:
    """Total PK 'siap transfer' yang belum ditransfer dari sebuah proses."""
    stmt = (
        select(func.coalesce(func.sum(MillingPkRouting.berat_kg), 0))
        .where(
            MillingPkRouting.milling_process_id == proc_id,
            MillingPkRouting.tujuan == "siap_transfer",
            MillingPkRouting.status_transfer == "menunggu",
        )
    )
    return float((await db.execute(stmt)).scalar_one())


@dataclass
class TransferResult:
    transfer: InternalTransfer
    kode_proses: str
    lokasi_label: str
    hpp_per_kg: float | None


async def create_internal_transfer(
    db: AsyncSession, *, user, kode_proses: str, lokasi_tujuan: str
) -> TransferResult:
    """Buat transfer semua PK siap-transfer dari sebuah milling ke Gudang 2."""
    if lokasi_tujuan not in _LOKASI:
        raise TransferError("Tujuan harus: Silo A, Silo B, atau ditumpuk.")
    proc = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode_proses)
        )
    ).scalars().first()
    if proc is None:
        raise TransferError(f"Proses {kode_proses} tidak ditemukan.")

    pending = await pending_transfer_kg(db, proc.id)
    if pending <= 0:
        raise TransferError(
            f"Tidak ada PK siap transfer dari {kode_proses}. "
            "Operator perlu menandai PK 'siap transfer' dulu saat milling."
        )

    hpp = await hpp_per_kg_pk(db, proc)
    now = now_local()
    transfer = InternalTransfer(
        kode_transfer=await next_transfer_code(db),
        milling_process_id=proc.id,
        drying_lot_id=proc.drying_lot_id,
        berat_kg=pending,
        lokasi_tujuan=lokasi_tujuan,
        hpp_per_kg=hpp,
        waktu=now,
        created_by=user.id,
        status="terkirim",
    )
    db.add(transfer)
    await db.flush()

    # Tandai semua routing siap-transfer yang menunggu -> ditransfer.
    await db.execute(
        update(MillingPkRouting)
        .where(
            MillingPkRouting.milling_process_id == proc.id,
            MillingPkRouting.tujuan == "siap_transfer",
            MillingPkRouting.status_transfer == "menunggu",
        )
        .values(status_transfer="ditransfer")
    )
    await log_activity(
        db, table_name="internal_transfers", record_id=transfer.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{transfer.kode_transfer} | {pending:.0f}kg -> {_LOKASI[lokasi_tujuan]} | hpp={hpp}",
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
    """PK yang menunggu untuk ditransfer, per proses milling."""
    rows = (
        await db.execute(
            select(
                MillingProcess.kode_proses,
                func.sum(MillingPkRouting.berat_kg),
            )
            .join(MillingProcess, MillingProcess.id == MillingPkRouting.milling_process_id)
            .where(
                MillingPkRouting.tujuan == "siap_transfer",
                MillingPkRouting.status_transfer == "menunggu",
            )
            .group_by(MillingProcess.kode_proses)
            .order_by(MillingProcess.kode_proses)
        )
    ).all()
    if not rows:
        return "🚚 Tidak ada PK yang menunggu transfer."
    total = sum(float(b) for _, b in rows)
    lines = [f"🚚 PK siap transfer ke Gudang 2: {_kg(total)}"]
    for kode, b in rows:
        lines.append(f"• dari {kode}: {_kg(float(b))}")
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
