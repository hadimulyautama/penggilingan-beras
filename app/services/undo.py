"""Undo tindakan terakhir — berbasis activity_logs.

v1: mendukung operasi PENGERINGAN (bentuk lot, gabung, kadar air, pendinginan,
selesai) + pembelian. Silo & milling menyusul. Admin bisa membatasi 'undo
terakhir oleh siapa' (operator gudang 1/2, staff, nama, atau semua).
"""
from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityLog,
    DryingCoolingLog,
    DryingLot,
    DryingLotBatch,
    DryingMoistureLog,
    MillingProcess,
    PurchaseBatch,
    PurchaseBatchVerification,
    SiloMovingLog,
    SiloStorage,
    User,
    Warehouse,
)
from app.services.activity_log import log_activity

# Tabel yang tindakannya bisa di-undo v1.
_UNDOABLE = {
    "drying_lots", "drying_moisture_logs", "drying_cooling_logs", "purchase_batches",
}


class UndoError(Exception):
    """Kesalahan undo dengan pesan siap-tampil (args[0])."""


# ─────────────────────── Resolusi 'oleh siapa' ───────────────────────
_SCOPE_LABEL = {
    "operator_gudang1": "operator Gudang 1",
    "operator_gudang2": "operator Gudang 2",
    "staff": "staff",
    "semua": "semua",
}


async def resolve_actor_ids(
    db: AsyncSession, *, scope: str | None, nama: str | None, self_id: int,
) -> tuple[list[int] | None, str | None]:
    """Kembalikan (daftar_id_user | None, label). None = tanpa filter (semua)."""
    if nama:
        ids = (
            await db.execute(
                select(User.id).where(func.lower(User.nama).like(f"%{nama.lower()}%"))
            )
        ).scalars().all()
        if not ids:
            raise UndoError(f"Pengguna '{nama}' tidak ditemukan.")
        return list(ids), f"'{nama}'"
    if scope in (None, "saya"):
        return [self_id], None
    if scope == "semua":
        return None, "semua"
    q = select(User.id)
    if scope.startswith("operator"):
        q = q.where(User.role == "operator")
        gud = 1 if scope == "operator_gudang1" else 2 if scope == "operator_gudang2" else None
        if gud:
            wh = (
                await db.execute(
                    select(Warehouse.id).where(Warehouse.nama_gudang.like(f"Gudang {gud}%"))
                )
            ).scalars().first()
            if wh:
                q = q.where(User.default_warehouse_id == wh)
    elif scope == "staff":
        q = q.where(User.role == "staff")
    ids = (await db.execute(q)).scalars().all()
    return list(ids), _SCOPE_LABEL.get(scope, scope)


# ─────────────────────────── Reversal ───────────────────────────
async def _lot_or_error(db: AsyncSession, lot_id: int) -> DryingLot:
    lot = await db.get(DryingLot, lot_id)
    if lot is None:
        raise UndoError("Lot sudah tidak ada (mungkin sudah dibatalkan).")
    return lot


async def _guard_lot_belum_lanjut(db: AsyncSession, lot_id: int, kode: str) -> None:
    in_silo = (
        await db.execute(select(SiloStorage.id).where(SiloStorage.drying_lot_id == lot_id))
    ).first()
    if in_silo:
        raise UndoError(f"Lot {kode} sudah masuk silo — tidak bisa dibatalkan.")
    milled = (
        await db.execute(select(MillingProcess.id).where(MillingProcess.drying_lot_id == lot_id))
    ).first()
    if milled:
        raise UndoError(f"Lot {kode} sudah digiling — tidak bisa dibatalkan.")


async def _undo_lot_create(db: AsyncSession, lot_id: int) -> str:
    lot = await _lot_or_error(db, lot_id)
    if lot.status != "proses":
        raise UndoError(f"Lot {lot.kode_lot} sudah {lot.status} — tidak bisa dibatalkan.")
    await _guard_lot_belum_lanjut(db, lot_id, lot.kode_lot)
    bids = (
        await db.execute(
            select(DryingLotBatch.purchase_batch_id).where(DryingLotBatch.drying_lot_id == lot_id)
        )
    ).scalars().all()
    for bid in bids:
        b = await db.get(PurchaseBatch, bid)
        if b:
            b.status_batch = "baru"
    # Bersihkan referensi sebelum hapus lot.
    await db.execute(delete(DryingLotBatch).where(DryingLotBatch.drying_lot_id == lot_id))
    await db.execute(delete(DryingMoistureLog).where(DryingMoistureLog.drying_lot_id == lot_id))
    await db.execute(delete(DryingCoolingLog).where(DryingCoolingLog.drying_lot_id == lot_id))
    await db.execute(delete(SiloMovingLog).where(SiloMovingLog.drying_lot_id == lot_id))
    kode = lot.kode_lot
    await db.delete(lot)
    return f"✓ Dibatalkan: pembentukan lot {kode} — {len(bids)} batch kembali ke 'baru'."


async def _undo_lot_merge(db: AsyncSession, lot_id: int, new_value: str | None) -> str:
    lot = await _lot_or_error(db, lot_id)
    if lot.status != "proses":
        raise UndoError(f"Lot {lot.kode_lot} sudah {lot.status} — tidak bisa dibatalkan.")
    m = re.search(r"\+(\d+)\s*batch", new_value or "")
    n = int(m.group(1)) if m else 1
    rows = (
        await db.execute(
            select(DryingLotBatch)
            .where(DryingLotBatch.drying_lot_id == lot_id)
            .order_by(DryingLotBatch.id.desc())
            .limit(n)
        )
    ).scalars().all()
    kodes: list[str] = []
    for r in rows:
        b = await db.get(PurchaseBatch, r.purchase_batch_id)
        if b:
            b.status_batch = "baru"
            kodes.append(b.kode_batch)
        await db.delete(r)
    return f"✓ Dibatalkan: penggabungan {len(rows)} batch ke {lot.kode_lot} ({', '.join(kodes)} kembali ke 'baru')."


async def _undo_finish_drying(db: AsyncSession, lot_id: int) -> str:
    lot = await _lot_or_error(db, lot_id)
    if lot.status != "selesai":
        raise UndoError(f"Lot {lot.kode_lot} tidak dalam status selesai.")
    await _guard_lot_belum_lanjut(db, lot_id, lot.kode_lot)
    lot.status = "proses"
    lot.waktu_selesai_pengeringan = None
    return f"✓ Dibatalkan: penandaan selesai {lot.kode_lot} (kembali 'proses')."


async def _undo_last_moisture(db: AsyncSession, lot_id: int) -> str:
    log = (
        await db.execute(
            select(DryingMoistureLog)
            .where(DryingMoistureLog.drying_lot_id == lot_id)
            .order_by(DryingMoistureLog.waktu_update.desc())
            .limit(1)
        )
    ).scalars().first()
    if log is None:
        raise UndoError("Tidak ada log kadar air untuk dibatalkan.")
    lot = await db.get(DryingLot, lot_id)
    await db.delete(log)
    return f"✓ Dibatalkan: log kadar air terakhir {lot.kode_lot if lot else ''}.".strip()


async def _undo_last_cooling(db: AsyncSession, lot_id: int) -> str:
    log = (
        await db.execute(
            select(DryingCoolingLog)
            .where(DryingCoolingLog.drying_lot_id == lot_id)
            .order_by(DryingCoolingLog.waktu.desc())
            .limit(1)
        )
    ).scalars().first()
    if log is None:
        raise UndoError("Tidak ada log pendinginan untuk dibatalkan.")
    lot = await db.get(DryingLot, lot_id)
    await db.delete(log)
    return f"✓ Dibatalkan: log pendinginan terakhir {lot.kode_lot if lot else ''}.".strip()


async def _undo_purchase(db: AsyncSession, batch_id: int) -> str:
    b = await db.get(PurchaseBatch, batch_id)
    if b is None:
        raise UndoError("Batch sudah tidak ada.")
    if b.status_batch != "baru":
        raise UndoError(f"{b.kode_batch} sudah diproses ({b.status_batch}) — tidak bisa dibatalkan.")
    in_lot = (
        await db.execute(select(DryingLotBatch.id).where(DryingLotBatch.purchase_batch_id == batch_id))
    ).first()
    if in_lot:
        raise UndoError(f"{b.kode_batch} sudah masuk lot pengeringan — tidak bisa dibatalkan.")
    await db.execute(
        delete(PurchaseBatchVerification).where(PurchaseBatchVerification.purchase_batch_id == batch_id)
    )
    kode = b.kode_batch
    await db.delete(b)
    return f"✓ Dibatalkan: input pembelian {kode}."


async def _undo_one(db: AsyncSession, log: ActivityLog) -> str:
    t, rid, act = log.table_name, log.record_id, log.action
    if t == "drying_lots" and act == "INSERT":
        return await _undo_lot_create(db, rid)
    if t == "drying_lots" and act == "UPDATE" and log.field_name == "status":
        return await _undo_finish_drying(db, rid)
    if t == "drying_lots" and act == "UPDATE":
        return await _undo_lot_merge(db, rid, log.new_value)
    if t == "drying_moisture_logs" and act == "INSERT":
        return await _undo_last_moisture(db, rid)
    if t == "drying_cooling_logs" and act == "INSERT":
        return await _undo_last_cooling(db, rid)
    if t == "purchase_batches" and act == "INSERT":
        return await _undo_purchase(db, rid)
    raise UndoError(
        f"Tindakan terakhir ({t}) belum bisa di-undo otomatis — fitur menyusul. "
        "Untuk sekarang koreksi lewat admin."
    )


async def undo_last(
    db: AsyncSession, *, actor, actor_ids: list[int] | None, scope_label: str | None,
) -> str:
    """Batalkan tindakan (undoable) TERAKHIR dari actor_ids. None = semua user."""
    q = select(ActivityLog).where(
        ActivityLog.table_name.in_(_UNDOABLE),
        ActivityLog.action.in_(["INSERT", "UPDATE"]),
    )
    if actor_ids is not None:
        if not actor_ids:
            raise UndoError("Tidak ada pengguna yang cocok untuk di-undo.")
        q = q.where(ActivityLog.changed_by.in_(actor_ids))
    q = q.order_by(ActivityLog.waktu_perubahan.desc(), ActivityLog.id.desc()).limit(1)
    log = (await db.execute(q)).scalars().first()
    if log is None:
        suffix = f" oleh {scope_label}" if scope_label else ""
        raise UndoError(f"Tidak ada input terakhir yang bisa dibatalkan{suffix}.")

    msg = await _undo_one(db, log)
    # Cegah double-undo: hapus entri yang diproses + catat jejak undo.
    t, rid = log.table_name, log.record_id
    await db.delete(log)
    await log_activity(
        db, table_name="undo", record_id=rid, action="UNDO",
        changed_by=actor.id, new_value=f"undo {t}#{rid}",
    )
    await db.commit()
    return msg
