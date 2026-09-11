"""Undo tindakan terakhir — berbasis activity_logs.

v1: mendukung operasi PENGERINGAN (bentuk lot, gabung, kadar air, pendinginan,
selesai) + pembelian. Silo & milling menyusul. Admin bisa membatasi 'undo
terakhir oleh siapa' (operator gudang 1/2, staff, nama, atau semua).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

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
    PkGudang2Intake,
    PkPurchaseBatch,
    PkPurchaseVerification,
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
    "pk_purchase_batches", "pk_purchase_verifications", "pk_gudang2_intakes",
}

#: Label ramah per tabel — untuk pesan "belum bisa di-undo" MAUPUN untuk
#: memberitahu apa yang akan dibatalkan sebelum tombolnya ditekan.
#:
#: Mencakup tabel yang didukung dan yang tidak. Dulu hanya yang tidak
#: didukung, karena satu-satunya tempat label dipakai adalah pesan penolakan;
#: sejak ada pratinjau, yang didukung justru yang paling sering ditampilkan.
#: Lewat ini, tindakan tak bisa dibatalkan lagi — lihat `undo_last`.
BATAS_UNDO = timedelta(hours=48)

_TABLE_LABEL = {
    # Bisa dibatalkan
    "drying_lots": "lot pengeringan",
    "drying_moisture_logs": "catatan kadar air",
    "drying_cooling_logs": "catatan pendinginan",
    "purchase_batches": "gabah masuk",
    "silo_storage": "isi silo",
    "milling_process": "proses giling",
    "internal_transfers": "pemindahan PK",
    "milling_qc_logs": "QC giling",
    "milling_process_verifications": "verifikasi output giling",
    "milling_progress_logs": "hasil giling",
    "silo_moving_logs": "pemindahan silo",
    "pk_purchase_batches": "PK luar masuk",
    "pk_purchase_verifications": "verifikasi harga PK luar",
    "pk_gudang2_intakes": "PK masuk Gudang 2",
    # Belum bisa dibatalkan
    # Jeda tidak dibatalkan lewat undo: yang benar bukan menghapus catatan
    # berhentinya melainkan MELANJUTKAN prosesnya, dan itu punya aksinya
    # sendiri. Berhenti yang dihapus membuat jam berjalan ikut berbohong.
    "jeda_proses": "proses berhenti sementara",
    # Setelan tidak dibatalkan lewat undo: yang benar adalah mengubahnya
    # kembali di layar Pengaturan, dan itu meninggalkan jejaknya sendiri.
    "setelan_pabrik": "setelan pabrik",
    # Pengelolaan akun juga tak dibatalkan lewat undo — membatalkan "reset
    # sandi" berarti mengembalikan sandi yang sudah tidak berlaku. Labelnya
    # tetap ada karena jejaknya MUNCUL di layar List audit, dan baris yang
    # berbunyi "produksi_akun" di sana tak menolong siapa pun.
    "produksi_akun": "akun & login",
    "polishing_process": "penyosohan", "polishing_output_logs": "hasil penyosohan",
    "polishing_silo_usage": "penyosohan", "finished_goods": "stok barang jadi",
    "packaging_stock": "stok kemasan", "beras_stock": "stok beras",
    "packaging_purchases": "pembelian karung",
    "outgoing_records": "barang keluar",
    "byproduct_prices": "harga hasil samping",
    "purchase_batch_verifications": "verifikasi harga gabah",
    "finished_goods_stock": "stok barang jadi",
    "byproduct_stock": "stok hasil samping",
    "pk_tumpukan_to_silo": "PK tumpukan ke silo",
}


def label_tabel(nama: str) -> str:
    return _TABLE_LABEL.get(nama, nama)


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


async def _undo_penempatan(db: AsyncSession, batch_id: int) -> str:
    """Batalkan PENEMPATAN gabah: masuk mesin pengering, atau ditumpuk.

    Cabang ini pernah tidak ada, dan akibatnya tombol Batalkan di List audit
    menolak dengan "belum bisa di-undo otomatis — fitur menyusul" untuk
    tindakan yang paling sering dilakukan orang. Yang tercatat sebagai
    `purchase_batches` INSERT adalah pembuatan batch-nya; penempatannya
    tercatat sebagai UPDATE terpisah, dan itulah yang berdiri paling atas di
    daftar sesudah gabah masuk.

    Gabah dikembalikan ke keadaan "belum punya tempat" — ia muncul lagi di
    antrean, dan tujuannya bisa dipilih ulang. Batch-nya sendiri TIDAK
    dihapus: yang salah tempatnya, bukan kedatangannya, dan menghapus batch
    berarti tiketnya ikut terlepas padahal truknya sungguh datang.
    """
    b = await db.get(PurchaseBatch, batch_id)
    if b is None:
        raise UndoError("Batch sudah tidak ada.")
    if b.status_batch == "baru":
        raise UndoError(f"{b.kode_batch} memang belum ditempatkan.")
    if b.status_batch not in ("di_dryer", "ditumpuk"):
        raise UndoError(
            f"{b.kode_batch} sudah diproses ({b.status_batch}) — "
            "batalkan dulu langkah sesudahnya."
        )
    in_lot = (await db.execute(
        select(DryingLotBatch.id).where(DryingLotBatch.purchase_batch_id == batch_id)
    )).first()
    if in_lot:
        raise UndoError(
            f"{b.kode_batch} sudah masuk lot pengeringan — batalkan lotnya dulu."
        )
    semula = b.status_batch
    b.status_batch = "baru"
    b.dryer_id = None
    dari = "mesin pengering" if semula == "di_dryer" else "tumpukan"
    return (f"✓ Dibatalkan: {b.kode_batch} dikeluarkan dari {dari} — "
            "kembali menunggu ditentukan tempatnya.")


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


# ── PK luar (Gudang 2) ──
async def _undo_pk_purchase(db: AsyncSession, batch_id: int) -> str:
    b = await db.get(PkPurchaseBatch, batch_id)
    if b is None:
        raise UndoError("PK luar sudah tidak ada.")
    intake = (
        await db.execute(
            select(PkGudang2Intake.id).where(PkGudang2Intake.pk_purchase_batch_id == batch_id)
        )
    ).first()
    if intake:
        raise UndoError(
            f"{b.kode_batch} sudah dimasukkan ke silo/tumpukan — batalkan pemasukannya dulu."
        )
    await db.execute(
        delete(PkPurchaseVerification).where(
            PkPurchaseVerification.pk_purchase_batch_id == batch_id
        )
    )
    kode = b.kode_batch
    await db.delete(b)
    return f"✓ Dibatalkan: catat PK luar {kode}."


async def _undo_pk_verif(db: AsyncSession, batch_id: int, field_name: str | None) -> str:
    verif = (
        await db.execute(
            select(PkPurchaseVerification).where(
                PkPurchaseVerification.pk_purchase_batch_id == batch_id
            )
        )
    ).scalars().first()
    b = await db.get(PkPurchaseBatch, batch_id)
    if verif is None or b is None:
        raise UndoError("Data PK luar sudah tidak ada.")
    if field_name == "harga":
        verif.harga_per_kg = None
        verif.total_biaya = None
        verif.metode_harga = None
        verif.potongan_kg = None
        verif.potongan_alasan = None
        b.flag_unverified = True
        # Balik snapshot HPP intake yang tadi di-backfill.
        intakes = (
            await db.execute(
                select(PkGudang2Intake).where(
                    PkGudang2Intake.pk_purchase_batch_id == batch_id
                )
            )
        ).scalars().all()
        for it in intakes:
            it.hpp_per_kg = None
            it.flag_hpp_belum_tersedia = True
        return f"✓ Dibatalkan: verifikasi harga PK {b.kode_batch} (harga dikosongkan)."
    # default: undo input kualitas
    verif.kadar_air = None
    verif.broken_persen = None
    verif.penyusutan_persen = None
    verif.butir_kuning = None
    verif.catatan_lab = None
    return f"✓ Dibatalkan: input kualitas PK {b.kode_batch}."


async def _undo_pk_intake(db: AsyncSession, intake_id: int) -> str:
    it = await db.get(PkGudang2Intake, intake_id)
    if it is None:
        raise UndoError("Pemasukan PK sudah tidak ada.")
    lok = {"silo_a": "Silo A", "silo_b": "Silo B", "ditumpuk": "tumpukan"}.get(
        it.tujuan, it.tujuan)
    b = await db.get(PkPurchaseBatch, it.pk_purchase_batch_id) if it.pk_purchase_batch_id else None
    await db.delete(it)
    if b:
        b.status_batch = "diterima"  # kembali ke 'sudah masuk, belum ditempatkan'
        return f"✓ Dibatalkan: PK {b.kode_batch} dimasukkan ke {lok}."
    return f"✓ Dibatalkan: pemasukan PK ke {lok}."


#: Tag aksi → penangan pembatalan. Disebut saat aksinya DIBUAT, jadi tak ada
#: yang perlu ditebak saat membatalkan.
_PENANGAN_TAG = {
    "ubah_target": "_undo_ubah_target",
    "silo_masuk": "_undo_masuk_silo_baris",
    "silo_gabung": "_undo_silo_merge_baris",
}


async def _undo_one(db: AsyncSession, log: ActivityLog) -> str:
    # ── Tag lebih dulu, tebakan belakangan ──
    #
    # Tebakan dari nama tabel & kolom salah persis pada kasus yang paling
    # mudah keliru: "ubah target kadar air" dan "gabungkan batch ke lot"
    # sama-sama UPDATE pada `drying_lots`, jadi keduanya jatuh ke penangan
    # yang sama. Membatalkan perubahan target justru MENGELUARKAN gabah dari
    # lot yang sedang dikeringkan, dan targetnya tak kembali.
    #
    # Tebakan lamanya DIPERTAHANKAN untuk baris yang dibuat sebelum tag ada —
    # mereka memang tak punya tag, dan menolak membatalkannya berarti
    # mematikan tombol untuk pekerjaan hari ini.
    tag = getattr(log, "aksi", None)
    if tag == "ubah_target":
        return await _undo_ubah_target(db, log)
    if tag == "silo_masuk":
        return await _undo_masuk_silo_baris(db, log.record_id)
    if tag == "silo_gabung":
        return await _undo_silo_merge_baris(db, log.record_id)

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
    if t == "purchase_batches" and act == "UPDATE":
        return await _undo_penempatan(db, rid)
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
    if t == "pk_purchase_batches" and act == "INSERT":
        return await _undo_pk_purchase(db, rid)
    if t == "pk_purchase_verifications":
        return await _undo_pk_verif(db, rid, log.field_name)
    if t == "pk_gudang2_intakes" and act == "INSERT":
        return await _undo_pk_intake(db, rid)
    raise UndoError(
        f"Tindakan terakhir ({_TABLE_LABEL.get(t, t)}) belum bisa di-undo otomatis — "
        "fitur menyusul. Untuk sekarang koreksi lewat admin."
    )


async def _undo_ubah_target(db: AsyncSession, log: ActivityLog) -> str:
    """Kembalikan target kadar air ke nilai sebelumnya — itu saja.

    Dulu perubahan target jatuh ke `_undo_lot_merge`, yang mengeluarkan batch
    TERAKHIR dari lot. Pratinjaunya berkata "lot pengeringan · 13.0"; yang
    terjadi adalah GB-02 kembali ke status "baru" tanpa lot, sementara
    targetnya tetap 13.0. Dua kerusakan sekaligus dari satu ketukan.
    """
    lot = await _lot_or_error(db, log.record_id)
    lama = log.old_value
    lot.target_kadar_air = float(lama) if lama not in (None, "", "None") else None
    sebut = f"{float(lama):g}%" if lot.target_kadar_air is not None else "kosong"
    return f"Target kadar air {lot.kode_lot} dikembalikan ke {sebut}."


async def _undo_masuk_silo_baris(db: AsyncSession, storage_id: int) -> str:
    """Batalkan SATU baris penyimpanan — yang ini, bukan yang terbaru.

    `record_id` dulu berisi id SILO, jadi pembatalan mengambil baris terbaru
    di silo itu: milik siapa pun yang terakhir mengisi. Budi membatalkan
    entrinya sendiri dan yang hilang entri Sari.
    """
    baris = await db.get(SiloStorage, storage_id)
    if baris is None:
        raise UndoError("Baris penyimpanan itu sudah tidak ada.")
    await _tolak_bila_sudah_dipakai(db, baris)
    silo = await db.get(Silo, baris.silo_id)
    if baris.drying_lot_id:
        await _revert_lot_batches(db, baris.drying_lot_id, "selesai")
    if baris.purchase_batch_id:
        b = await db.get(PurchaseBatch, baris.purchase_batch_id)
        if b is not None:
            b.status_batch = "baru"
    await db.delete(baris)
    return f"Pemasukan ke Silo {silo.nama_silo if silo else '?'} dibatalkan."


async def _undo_silo_merge_baris(db: AsyncSession, storage_id: int) -> str:
    """Sama, untuk penggabungan."""
    return await _undo_masuk_silo_baris(db, storage_id)


async def _tolak_bila_sudah_dipakai(db: AsyncSession, baris) -> None:
    """Tolak pembatalan bila isinya sudah TERPAKAI di hilir.

    Temuan QA P-K-10: pembatalan tak pernah melihat apa yang terjadi
    sesudahnya. Membatalkan pemasukan silo yang isinya sudah digiling
    meninggalkan proses giling yang sumbernya tak ada — dan angka rendemennya
    terbaca melambung tanpa ada yang tahu sebabnya.
    """
    from app.models import MillingProcessSource

    dipakai = (await db.execute(
        select(MillingProcessSource.milling_process_id)
        .where(MillingProcessSource.silo_storage_id == baris.id).limit(1)
    )).scalars().first()
    if dipakai is not None:
        proses = await db.get(MillingProcess, dipakai)
        raise UndoError(
            f"Tak bisa dibatalkan: isinya sudah dipakai giling "
            f"{proses.kode_proses if proses else f'#{dipakai}'}. "
            "Batalkan gilingnya lebih dulu, atau perbaiki lewat koreksi."
        )


async def id_log_terakhir(db: AsyncSession, user_id: int) -> int | None:
    """Id jejak terakhir milik satu orang — untuk tombol BATALKAN di kabar.

    Dipanggil tepat sesudah aksinya tersimpan, jadi yang ditemukan memang
    baris yang barusan ditulis. Id-nya dibawa ke layar supaya tombol BATALKAN
    membatalkan CATATAN ITU, bukan "yang terakhir" — antara menekan dan
    membatalkan, rekan di pos sebelah bisa saja sudah mencatat sesuatu.
    """
    return (await db.execute(
        select(ActivityLog.id)
        .where(ActivityLog.changed_by == user_id,
               ActivityLog.table_name != "undo",
               ActivityLog.dibatalkan_pada.is_(None))
        .order_by(ActivityLog.waktu_perubahan.desc(), ActivityLog.id.desc())
        .limit(1)
    )).scalars().first()


async def _log_terakhir(db: AsyncSession, actor_ids: list[int] | None):
    """Tindakan terakhir yang akan dibatalkan — SATU kueri untuk dua pemakai.

    Pratinjau dan pembatalan wajib menunjuk tindakan yang sama. Bila keduanya
    menyusun kueri sendiri-sendiri, suatu saat salah satunya akan diubah dan
    orang akan menekan tombol untuk membatalkan sesuatu yang lain dari yang
    tertulis di layar.
    """
    q = select(ActivityLog).where(
        ActivityLog.action.in_(["INSERT", "UPDATE"]),
        ActivityLog.table_name != "undo",
        # Yang sudah dibatalkan bukan lagi "tindakan terakhir". Dulu ia hilang
        # dari tabel sehingga tak perlu disaring; sekarang ia tinggal sebagai
        # jejak, dan jejak bukan pekerjaan.
        ActivityLog.dibatalkan_pada.is_(None),
    )
    if actor_ids is not None:
        if not actor_ids:
            raise UndoError("Tidak ada pengguna yang cocok untuk di-undo.")
        q = q.where(ActivityLog.changed_by.in_(actor_ids))
    q = q.order_by(ActivityLog.waktu_perubahan.desc(), ActivityLog.id.desc()).limit(1)
    return (await db.execute(q)).scalars().first()


@dataclass
class Pratinjau:
    """Apa yang akan dibatalkan — dibaca sebelum ada yang berubah."""

    log_id: int
    tabel: str
    label: str
    ringkas: str
    oleh: str
    waktu: datetime
    didukung: bool


async def pratinjau_terakhir(
    db: AsyncSession, *, actor_ids: list[int] | None
) -> Pratinjau | None:
    """Lihat tindakan terakhir tanpa menyentuhnya. None = tidak ada.

    Jalur bot langsung membatalkan lalu memberi tahu apa yang barusan hilang.
    Di layar itu tidak cukup: tombol yang tidak menyebutkan akibatnya akan
    ditekan untuk mencoba-coba. Karena itu yang ditawarkan adalah kalimat
    lengkapnya, dan yang ditekan orang adalah kalimat itu.
    """
    log = await _log_terakhir(db, actor_ids)
    if log is None:
        return None
    nama = (await db.execute(
        select(User.nama).where(User.id == log.changed_by)
    )).scalars().first()
    ringkas = (log.new_value or "").strip() or f"#{log.record_id}"
    return Pratinjau(
        log_id=log.id,
        tabel=log.table_name,
        label=label_tabel(log.table_name),
        ringkas=ringkas.split("|")[0].strip()[:60],
        oleh=nama or "?",
        waktu=log.waktu_perubahan,
        didukung=log.table_name in _UNDOABLE,
    )


async def undo_last(
    db: AsyncSession, *, actor, actor_ids: list[int] | None, scope_label: str | None,
    log_id: int | None = None,
) -> str:
    """Batalkan tindakan yang DITAMPILKAN — bukan "yang terakhir" lagi.

    `log_id` datang dari pratinjau yang dibaca orangnya. Dulu tak ada: layar
    menampilkan kalimatnya, POST hanya mengirim lingkupnya, dan fungsi ini
    mencari "aksi terakhir" SEKALI LAGI saat mengeksekusi. Bila ada aksi lain
    masuk di antara melihat dan menekan — dan di pos yang sibuk itu biasa —
    yang dibatalkan adalah aksi itu. Orang membaca satu kalimat lalu
    membatalkan kalimat yang lain, tanpa satu pun tanda.

    Barisnya DIKUNCI lalu diperiksa ulang: masih yang terbaru dalam lingkup
    ini? Kalau tidak, ditolak sambil menyebut apa yang menyusul.
    """
    if log_id is not None:
        log = (await db.execute(
            select(ActivityLog).where(ActivityLog.id == log_id).with_for_update()
        )).scalars().first()
        if log is None:
            raise UndoError("Tindakan itu sudah tidak ada.")
        if log.dibatalkan_pada is not None:
            raise UndoError("Tindakan itu sudah dibatalkan sebelumnya.")
        terbaru = await _log_terakhir(db, actor_ids)
        if terbaru is not None and terbaru.id != log.id:
            raise UndoError(
                f"Sudah berubah: yang terakhir sekarang "
                f"'{(terbaru.new_value or '').split('|')[0].strip()[:50]}'. "
                "Buka lagi daftarnya supaya yang dibatalkan benar-benar yang "
                "Anda maksud."
            )
    else:
        log = await _log_terakhir(db, actor_ids)
    if log is None:
        suffix = f" oleh {scope_label}" if scope_label else ""
        raise UndoError(f"Tidak ada input terakhir yang bisa dibatalkan{suffix}.")
    # ── Batas 48 jam ──
    # Bukan aturan tampilan: angka hari kemarin sudah masuk laporan dan sudah
    # dipakai orang lain memutuskan. Membiarkannya berubah berarti laporan
    # yang sama bisa berbeda isinya tiap kali dibuka. Salah yang baru ketahuan
    # setelah lewat diperbaiki dengan catatan koreksi baru — bukan dengan
    # membatalkan yang lama.
    #
    # Dijaga DI SINI, bukan di layar: menyembunyikan tombol bukan penjagaan,
    # dan jalur bot memakai fungsi yang sama.
    from app.database import now_local

    umur = now_local() - log.waktu_perubahan
    if umur > BATAS_UNDO:
        jam = umur.total_seconds() / 3600
        raise UndoError(
            f"Tindakan itu sudah {jam:.0f} jam lalu — lewat batas "
            f"{BATAS_UNDO.total_seconds() / 3600:.0f} jam. "
            "Perbaiki dengan catatan baru, bukan dengan membatalkan yang lama."
        )
    if log.table_name not in _UNDOABLE:
        raise UndoError(
            f"Tindakan terakhir ({label_tabel(log.table_name)}) "
            "belum bisa dibatalkan otomatis — koreksi lewat admin."
        )

    msg = await _undo_one(db, log)
    # ── Jejaknya DITANDAI, bukan dihapus ──
    #
    # Dulu `db.delete(log)`, dan itu melanggar ARSITEKTUR §6: jejak audit
    # bersifat tambah-saja. Ia satu-satunya catatan siapa mengerjakan apa, dan
    # menghapusnya membuang bukti persis pada saat bukti itu dicari — "kenapa
    # angka kemarin berubah?" tak bisa dijawab bila jejaknya ikut hilang
    # bersama yang dibatalkan.
    #
    # Penandanya sekaligus mencegah pembatalan ganda, tugas yang dulu dipikul
    # penghapusan.
    t, rid = log.table_name, log.record_id
    log.dibatalkan_pada = now_local()
    log.dibatalkan_oleh = actor.id
    await log_activity(
        db, table_name="undo", record_id=rid, action="UNDO",
        changed_by=actor.id, new_value=f"undo {t}#{rid}",
        aksi="undo",
    )
    await db.commit()
    return msg
