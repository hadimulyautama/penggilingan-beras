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
    InternalTransfer,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchVerification,
    Silo,
    SiloMovingLog,
    SiloStorage,
    User,
    Warehouse,
)
from app.services.activity_log import log_activity

# Tabel yang tindakannya bisa di-undo.
_UNDOABLE = {
    "drying_lots", "drying_moisture_logs", "drying_cooling_logs", "purchase_batches",
    "silo_storage", "milling_process", "internal_transfers", "milling_qc_logs",
    "milling_process_verifications", "milling_progress_logs", "silo_moving_logs",
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


# ── Silo ──
async def _revert_lot_batches(db: AsyncSession, lot_id: int, status: str) -> None:
    bids = (
        await db.execute(
            select(DryingLotBatch.purchase_batch_id).where(DryingLotBatch.drying_lot_id == lot_id)
        )
    ).scalars().all()
    for bid in bids:
        b = await db.get(PurchaseBatch, bid)
        if b:
            b.status_batch = status


async def _undo_masuk_silo(db: AsyncSession, silo_id: int) -> str:
    st = (
        await db.execute(
            select(SiloStorage)
            .where(SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi")
            .order_by(SiloStorage.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if st is None:
        raise UndoError("Tidak ada gabah masuk silo untuk dibatalkan.")
    milled = (
        await db.execute(select(MillingProcess.id).where(MillingProcess.silo_storage_id == st.id))
    ).first()
    if milled:
        raise UndoError("Isi silo sudah digiling — tidak bisa dibatalkan.")
    lot_to_delete = None
    if st.tipe_masuk == "langsung_kering" and st.drying_lot_id:
        # Lot ini DIBUAT oleh intake (gabah kering langsung) -> hapus juga.
        await _revert_lot_batches(db, st.drying_lot_id, "baru")
        await db.execute(
            delete(DryingLotBatch).where(DryingLotBatch.drying_lot_id == st.drying_lot_id)
        )
        lot_to_delete = st.drying_lot_id
    elif st.drying_lot_id:
        # Lot dari pengeringan -> tetap ada, batch balik 'dikeringkan'.
        await _revert_lot_batches(db, st.drying_lot_id, "dikeringkan")
    elif st.purchase_batch_id:
        b = await db.get(PurchaseBatch, st.purchase_batch_id)
        if b:
            b.status_batch = "baru"
    silo = await db.get(Silo, silo_id)
    if silo:
        silo.status = "kosong"
    nama = silo.nama_silo if silo else "silo"
    await db.delete(st)
    if lot_to_delete is not None:
        lot = await db.get(DryingLot, lot_to_delete)
        if lot:
            await db.delete(lot)
    return f"✓ Dibatalkan: gabah masuk {nama}."


async def _undo_silo_merge(db: AsyncSession, silo_id: int) -> str:
    """Undo penggabungan batch kering ke lot yang ada di silo: lepas batch terakhir."""
    st = (
        await db.execute(
            select(SiloStorage)
            .where(SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi")
            .order_by(SiloStorage.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if st is None or not st.drying_lot_id:
        raise UndoError("Tidak ada penggabungan silo untuk dibatalkan.")
    milled = (
        await db.execute(select(MillingProcess.id).where(MillingProcess.silo_storage_id == st.id))
    ).first()
    if milled:
        raise UndoError("Isi silo sudah digiling — tidak bisa dibatalkan.")
    row = (
        await db.execute(
            select(DryingLotBatch)
            .where(DryingLotBatch.drying_lot_id == st.drying_lot_id)
            .order_by(DryingLotBatch.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        raise UndoError("Tidak ada batch untuk dilepas.")
    b = await db.get(PurchaseBatch, row.purchase_batch_id)
    kode = b.kode_batch if b else "?"
    if b:
        b.status_batch = "baru"
    await db.delete(row)
    return f"✓ Dibatalkan: penggabungan {kode} ke lot di silo (kembali 'baru')."


async def _undo_keluar_silo(db: AsyncSession, silo_id: int) -> str:
    st = (
        await db.execute(
            select(SiloStorage)
            .where(SiloStorage.silo_id == silo_id, SiloStorage.status == "kosong")
            .order_by(SiloStorage.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if st is None:
        raise UndoError("Tidak ada pengosongan silo untuk dibatalkan.")
    st.status = "terisi"
    st.tanggal_keluar = None
    silo = await db.get(Silo, silo_id)
    if silo:
        silo.status = "terisi"
    return f"✓ Dibatalkan: pengosongan {silo.nama_silo if silo else 'silo'} (terisi lagi)."


# ── Milling ──
async def _undo_start_milling(db: AsyncSession, proc_id: int) -> str:
    proc = await db.get(MillingProcess, proc_id)
    if proc is None:
        raise UndoError("Proses giling sudah tidak ada.")
    if proc.status == "selesai":
        raise UndoError(f"{proc.kode_proses} sudah selesai — tidak bisa dibatalkan.")
    for M in (MillingProgressLog, MillingQcLog):
        exists = (
            await db.execute(select(M.id).where(M.milling_process_id == proc_id))
        ).first()
        if exists:
            raise UndoError(
                f"{proc.kode_proses} sudah ada progress/QC — batalkan itu dulu."
            )
    kode = proc.kode_proses
    await db.delete(proc)
    return f"✓ Dibatalkan: mulai giling {kode}."


async def _undo_finish_milling(db: AsyncSession, proc_id: int) -> str:
    proc = await db.get(MillingProcess, proc_id)
    if proc is None:
        raise UndoError("Proses giling sudah tidak ada.")
    if proc.status != "selesai":
        raise UndoError(f"{proc.kode_proses} tidak dalam status selesai.")
    trf = (
        await db.execute(select(InternalTransfer.id).where(InternalTransfer.milling_process_id == proc_id))
    ).first()
    if trf:
        raise UndoError(f"{proc.kode_proses} sudah ada transfer PK — tidak bisa dibatalkan.")
    proc.status = "proses"
    proc.waktu_selesai = None
    if proc.silo_storage_id:
        st = await db.get(SiloStorage, proc.silo_storage_id)
        if st:
            st.status = "terisi"
            st.tanggal_keluar = None
        silo = await db.get(Silo, proc.silo_id)
        if silo:
            silo.status = "terisi"
    if proc.drying_lot_id:
        await _revert_lot_batches(db, proc.drying_lot_id, "di_silo")
    elif proc.purchase_batch_id:
        b = await db.get(PurchaseBatch, proc.purchase_batch_id)
        if b:
            b.status_batch = "di_silo"
    return f"✓ Dibatalkan: selesai giling {proc.kode_proses} (kembali 'proses', silo terisi lagi)."


async def _undo_transfer(db: AsyncSession, transfer_id: int) -> str:
    """Batalkan transfer PK ke Gudang 2 — stok siap kirim kembali bertambah."""
    t = await db.get(InternalTransfer, transfer_id)
    if t is None:
        raise UndoError("Transfer sudah tidak ada.")
    proc = await db.get(MillingProcess, t.milling_process_id)
    kode = proc.kode_proses if proc else ""
    berat = float(t.berat_kg)
    label = _LOKASI_UNDO.get(t.lokasi_tujuan, t.lokasi_tujuan)
    await db.delete(t)
    kg = f"{berat:,.0f} kg".replace(",", ".")
    return (
        f"✓ Dibatalkan: transfer {t.kode_transfer} ({kg} PK dari {kode} → "
        f"{label} Gudang 2). Stok siap kirim {kode} kembali bertambah."
    ).strip()


_LOKASI_UNDO = {"silo_a": "Silo A", "silo_b": "Silo B", "ditumpuk": "tumpukan"}


async def _undo_last_progress(db: AsyncSession, proc_id: int) -> str:
    p = (
        await db.execute(
            select(MillingProgressLog)
            .where(MillingProgressLog.milling_process_id == proc_id)
            .order_by(MillingProgressLog.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if p is None:
        raise UndoError("Tidak ada progress giling untuk dibatalkan.")
    proc = await db.get(MillingProcess, proc_id)
    await db.delete(p)
    return f"✓ Dibatalkan: progress giling terakhir {proc.kode_proses if proc else ''}.".strip()


async def _undo_moving_log(db: AsyncSession, log_id: int) -> str:
    ml = await db.get(SiloMovingLog, log_id)
    if ml is None:
        raise UndoError("Catatan pemindahan sudah tidak ada.")
    tipe = ml.tipe
    await db.delete(ml)
    return f"✓ Dibatalkan: catatan pemindahan ({tipe})."


async def _undo_last_qc(db: AsyncSession, proc_id: int) -> str:
    q = (
        await db.execute(
            select(MillingQcLog)
            .where(MillingQcLog.milling_process_id == proc_id)
            .order_by(MillingQcLog.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if q is None:
        raise UndoError("Tidak ada QC untuk dibatalkan.")
    await db.delete(q)
    return "✓ Dibatalkan: QC milling terakhir."


async def _undo_verify_output(db: AsyncSession, proc_id: int) -> str:
    v = (
        await db.execute(
            select(MillingProcessVerification).where(
                MillingProcessVerification.milling_process_id == proc_id
            )
        )
    ).scalars().first()
    if v is None:
        raise UndoError("Tidak ada verifikasi output untuk dibatalkan.")
    await db.delete(v)
    return "✓ Dibatalkan: verifikasi output milling."


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
    if t == "silo_storage" and act == "INSERT":
        return await _undo_masuk_silo(db, rid)
    if t == "silo_storage" and act == "UPDATE" and log.field_name == "gabung":
        return await _undo_silo_merge(db, rid)
    if t == "silo_storage" and act == "UPDATE":
        return await _undo_keluar_silo(db, rid)
    if t == "milling_process" and act == "INSERT":
        return await _undo_start_milling(db, rid)
    if t == "milling_process" and act == "UPDATE":
        return await _undo_finish_milling(db, rid)
    if t == "milling_progress_logs" and act == "INSERT":
        return await _undo_last_progress(db, rid)
    if t == "silo_moving_logs" and act == "INSERT":
        return await _undo_moving_log(db, rid)
    if t == "internal_transfers" and act == "INSERT":
        return await _undo_transfer(db, rid)
    if t == "milling_qc_logs" and act == "INSERT":
        return await _undo_last_qc(db, rid)
    if t == "milling_process_verifications":
        return await _undo_verify_output(db, rid)
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
