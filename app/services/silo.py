"""Logika bisnis silo Gudang 1 (penyimpanan gabah kering)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLot,
    DryingLotBatch,
    PurchaseBatch,
    Silo,
    SiloMovingLog,
    SiloStorage,
    Supplier,
    Warehouse,
)
from app.services.activity_log import log_activity


class SiloError(Exception):
    """Kesalahan proses silo dengan pesan siap-tampil (args[0])."""


async def _g1_warehouse_id(db: AsyncSession) -> int:
    wid = (
        await db.execute(
            select(Warehouse.id).where(Warehouse.nama_gudang.like("Gudang 1%"))
        )
    ).scalars().first()
    if wid is None:
        raise SiloError("Data gudang 1 belum ada.")
    return wid


async def get_g1_silo(db: AsyncSession, letter: str) -> Silo | None:
    wid = await _g1_warehouse_id(db)
    stmt = select(Silo).where(
        Silo.warehouse_id == wid, Silo.nama_silo == f"Silo {letter}"
    )
    return (await db.execute(stmt)).scalars().first()


async def _active_storage(db: AsyncSession, silo_id: int) -> SiloStorage | None:
    stmt = select(SiloStorage).where(
        SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
    )
    return (await db.execute(stmt)).scalars().first()


async def _lot_kg(db: AsyncSession, lot_id: int) -> float:
    stmt = (
        select(func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0))
        .select_from(DryingLotBatch)
        .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
        .where(DryingLotBatch.drying_lot_id == lot_id)
    )
    return float((await db.execute(stmt)).scalar_one())


async def _lot_suppliers(db: AsyncSession, lot_id: int) -> list[str]:
    stmt = (
        select(Supplier.nama_supplier)
        .select_from(DryingLotBatch)
        .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
        .join(Supplier, PurchaseBatch.supplier_id == Supplier.id)
        .where(DryingLotBatch.drying_lot_id == lot_id)
        .distinct()
    )
    return list((await db.execute(stmt)).scalars().all())


def _fmt_kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


# ─────────────────────────── Masuk silo ───────────────────────────
@dataclass
class MasukResult:
    nama_silo: str
    isi: str
    kg: float
    tipe: str  # dari_pengeringan | langsung_kering


async def masuk_silo(
    db: AsyncSession,
    *,
    user,
    nama_silo: str | None,
    kode_lot: str | None,
    kode_batch: str | None,
) -> MasukResult:
    if not nama_silo:
        raise SiloError("Sebutkan silo A atau B, contoh: `masukkan LOT-... ke silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise SiloError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    occupied = await _active_storage(db, silo.id)
    if occupied:
        raise SiloError(f"Silo {nama_silo} sedang terisi — kosongkan dulu.")

    now = now_local()
    if kode_lot:
        lot = (
            await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode_lot))
        ).scalars().first()
        if lot is None:
            raise SiloError(f"Lot {kode_lot} tidak ditemukan.")
        if lot.status != "selesai":
            raise SiloError(f"Lot {kode_lot} belum selesai dikeringkan.")
        dup = (
            await db.execute(
                select(SiloStorage.id).where(
                    SiloStorage.drying_lot_id == lot.id, SiloStorage.status == "terisi"
                )
            )
        ).first()
        if dup:
            raise SiloError(f"Lot {kode_lot} sudah ada di silo.")
        kg = await _lot_kg(db, lot.id)
        db.add(
            SiloStorage(
                silo_id=silo.id,
                drying_lot_id=lot.id,
                tipe_masuk="dari_pengeringan",
                tanggal_masuk=now,
                input_by=user.id,
                status="terisi",
            )
        )
        # Batch di lot ikut berstatus di_silo.
        batch_ids = (
            await db.execute(
                select(DryingLotBatch.purchase_batch_id).where(
                    DryingLotBatch.drying_lot_id == lot.id
                )
            )
        ).scalars().all()
        for bid in batch_ids:
            b = await db.get(PurchaseBatch, bid)
            if b:
                b.status_batch = "di_silo"
        isi, tipe = kode_lot, "dari_pengeringan"

    elif kode_batch:
        batch = (
            await db.execute(
                select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode_batch)
            )
        ).scalars().first()
        if batch is None:
            raise SiloError(f"Batch {kode_batch} tidak ditemukan.")
        if batch.kondisi_gabah != "kering":
            raise SiloError(
                f"Batch {kode_batch} gabah basah — harus dikeringkan dulu, "
                "tidak bisa langsung ke silo."
            )
        in_lot = (
            await db.execute(
                select(DryingLotBatch.id).where(
                    DryingLotBatch.purchase_batch_id == batch.id
                )
            )
        ).first()
        if in_lot:
            raise SiloError(f"Batch {kode_batch} sudah masuk lot pengeringan.")
        dup = (
            await db.execute(
                select(SiloStorage.id).where(
                    SiloStorage.purchase_batch_id == batch.id,
                    SiloStorage.status == "terisi",
                )
            )
        ).first()
        if dup:
            raise SiloError(f"Batch {kode_batch} sudah ada di silo.")
        kg = float(batch.berat_total_kg)
        db.add(
            SiloStorage(
                silo_id=silo.id,
                purchase_batch_id=batch.id,
                tipe_masuk="langsung_kering",
                tanggal_masuk=now,
                input_by=user.id,
                status="terisi",
            )
        )
        batch.status_batch = "di_silo"
        isi, tipe = kode_batch, "langsung_kering"
    else:
        raise SiloError(
            "Sebutkan lot atau batch yang dimasukkan, contoh:\n"
            "`masukkan LOT-20260702-01 ke silo A`"
        )

    silo.status = "terisi"
    await log_activity(
        db,
        table_name="silo_storage",
        record_id=silo.id,
        action="INSERT",
        changed_by=user.id,
        new_value=f"Silo {nama_silo} <- {isi} ({tipe}, {kg:.0f}kg)",
    )
    await db.commit()
    return MasukResult(nama_silo=nama_silo, isi=isi, kg=kg, tipe=tipe)


# ─────────────────── Log pemindahan dryer -> silo ───────────────────
async def _lot_active_storage(db: AsyncSession, lot_id: int) -> SiloStorage | None:
    return (
        await db.execute(
            select(SiloStorage).where(
                SiloStorage.drying_lot_id == lot_id, SiloStorage.status == "terisi"
            )
        )
    ).scalars().first()


async def moving_started(
    db: AsyncSession, *, user, nama_silo: str | None, kode_lot: str | None
) -> tuple[str, str | None]:
    """Catat log 'mulai pemindahan' ke silo. Gabah masih di dryer."""
    if not kode_lot:
        raise SiloError(
            "Sebutkan lot-nya, contoh: `mulai pindah LOT-20260702-01 ke silo A`"
        )
    lot = (
        await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode_lot))
    ).scalars().first()
    if lot is None:
        raise SiloError(f"Lot {kode_lot} tidak ditemukan.")
    silo = await get_g1_silo(db, nama_silo) if nama_silo else None
    db.add(
        SiloMovingLog(
            drying_lot_id=lot.id,
            silo_id=silo.id if silo else None,
            tipe="mulai",
            waktu=now_local(),
            input_by=user.id,
        )
    )
    await db.commit()
    return lot.kode_lot, nama_silo


@dataclass
class MovingDoneResult:
    kode_lot: str
    nama_silo: str
    kondisi: str  # "intake" (baru masuk) | "already" (sudah tercatat sebelumnya)
    kg: float | None


async def moving_finished(
    db: AsyncSession, *, user, nama_silo: str | None, kode_lot: str | None
) -> MovingDoneResult:
    """Pemindahan ke silo selesai. Kondisional: intake bila belum, else log saja."""
    if not kode_lot:
        raise SiloError(
            "Sebutkan lot-nya, contoh: `pemindahan LOT-20260702-01 ke silo A selesai`"
        )
    lot = (
        await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode_lot))
    ).scalars().first()
    if lot is None:
        raise SiloError(f"Lot {kode_lot} tidak ditemukan.")

    existing = await _lot_active_storage(db, lot.id)
    if existing:
        # Sudah tercatat di silo -> cukup log 'selesai'.
        silo = await db.get(Silo, existing.silo_id)
        db.add(
            SiloMovingLog(
                drying_lot_id=lot.id, silo_id=existing.silo_id, tipe="selesai",
                waktu=now_local(), input_by=user.id,
            )
        )
        await db.commit()
        nama = silo.nama_silo.replace("Silo ", "") if silo else "-"
        return MovingDoneResult(kode_lot=lot.kode_lot, nama_silo=nama, kondisi="already", kg=None)

    # Belum di silo -> lakukan intake (state: di silo + dryer kosong).
    res = await masuk_silo(db, user=user, nama_silo=nama_silo, kode_lot=kode_lot, kode_batch=None)
    silo = await get_g1_silo(db, res.nama_silo)
    db.add(
        SiloMovingLog(
            drying_lot_id=lot.id, silo_id=silo.id if silo else None, tipe="selesai",
            waktu=now_local(), input_by=user.id,
        )
    )
    await db.commit()
    return MovingDoneResult(
        kode_lot=lot.kode_lot, nama_silo=res.nama_silo, kondisi="intake", kg=res.kg
    )


# ─────────────────────────── Keluar silo ───────────────────────────
async def keluar_silo(db: AsyncSession, *, user, nama_silo: str | None) -> str:
    if not nama_silo:
        raise SiloError("Sebutkan silo yang dikosongkan, contoh: `kosongkan silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise SiloError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    storage = await _active_storage(db, silo.id)
    if storage is None:
        raise SiloError(f"Silo {nama_silo} sudah kosong.")
    storage.status = "kosong"
    storage.tanggal_keluar = now_local()
    silo.status = "kosong"
    await log_activity(
        db,
        table_name="silo_storage",
        record_id=silo.id,
        action="UPDATE",
        changed_by=user.id,
        field_name="status",
        new_value="kosong",
    )
    await db.commit()
    return nama_silo


# ─────────────────────────── Laporan silo ───────────────────────────
async def laporan_silo(db: AsyncSession) -> str:
    wid = await _g1_warehouse_id(db)
    silos = (
        await db.execute(
            select(Silo).where(Silo.warehouse_id == wid).order_by(Silo.nama_silo)
        )
    ).scalars().all()
    if not silos:
        return "Belum ada silo di Gudang 1."
    now = now_local()
    lines = ["🏗️ Status silo Gudang 1:"]
    for silo in silos:
        cap = (
            f"maks {float(silo.kapasitas_ton):g} ton"
            if silo.kapasitas_ton is not None
            else "kapasitas belum diatur"
        )
        st = await _active_storage(db, silo.id)
        if st is None:
            lines.append(f"• {silo.nama_silo}: kosong ({cap})")
            continue
        jam = (now - st.tanggal_masuk).total_seconds() / 3600
        if st.drying_lot_id:
            lot = await db.get(DryingLot, st.drying_lot_id)
            kg = await _lot_kg(db, st.drying_lot_id)
            sups = ", ".join(await _lot_suppliers(db, st.drying_lot_id)) or "-"
            isi = f"{lot.kode_lot if lot else 'lot'} ({sups})"
        else:
            b = await db.get(PurchaseBatch, st.purchase_batch_id)
            sup = await db.get(Supplier, b.supplier_id) if b else None
            kg = float(b.berat_total_kg) if b else 0
            isi = f"{b.kode_batch if b else 'batch'} ({sup.nama_supplier if sup else '-'})"
        lines.append(
            f"• {silo.nama_silo}: terisi — {isi}, {_fmt_kg(kg)}, {jam:.0f} jam ({cap})"
        )
    return "\n".join(lines)
