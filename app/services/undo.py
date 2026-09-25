"""Undo tindakan terakhir — berbasis activity_logs.

v1: mendukung operasi PENGERINGAN (bentuk lot, gabung, kadar air, pendinginan,
selesai) + pembelian. Silo & milling menyusul. Admin bisa membatasi 'undo
terakhir oleh siapa' (operator gudang 1/2, staff, nama, atau semua).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_identitas import peran as _P

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
)
from app.services.activity_log import log_activity

# Tabel yang tindakannya bisa di-undo.
_UNDOABLE = {
    "drying_lots", "drying_moisture_logs", "drying_cooling_logs", "purchase_batches",
    "silo_storage", "milling_process", "internal_transfers", "milling_qc_logs",
    "milling_process_verifications", "milling_progress_logs", "silo_moving_logs",
    "pk_purchase_batches", "pk_purchase_verifications", "pk_gudang2_intakes",
    "pk_tumpukan_to_silo",
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
    "pk_tumpukan_to_silo": "PK tumpukan ke silo",
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
}


def label_tabel(nama: str) -> str:
    return _TABLE_LABEL.get(nama, nama)


class UndoError(Exception):
    """Kesalahan undo dengan pesan siap-tampil (args[0])."""


# ─────────────────────── Cakupan: catatan siapa, di gudang mana ───────────────────────
_SCOPE_LABEL = {
    "operator_gudang1": "operator Gudang 1",
    "operator_gudang2": "operator Gudang 2",
    "semua": "semua",
}
_SCOPE_GUDANG = {"operator_gudang1": _P.G1, "operator_gudang2": _P.G2}


@dataclass(frozen=True)
class Cakupan:
    """Catatan mana yang boleh dibatalkan: oleh siapa, dan di gudang mana.

    Dua saringan yang berdiri sendiri. `actor_ids` menyaring PENCATATNYA
    (None = siapa pun); `gudang` menyaring CATATANNYA lewat
    `activity_logs.gudang` (None = gudang mana pun).

    Dulu keduanya ditumpuk pada satu daftar orang: "operator Gudang 1" =
    operator yang HARI INI berprofil Gudang 1. Sejak operator boleh berpindah
    gudang untuk saling menggantikan, daftar itu berubah surut — pada hari
    Rusdi menggantikan rekannya di Gudang 2, cakupan "operator Gudang 1"
    berhenti mengenai catatan lamanya, dan cakupan "operator Gudang 2" ikut
    menyapu seluruh pekerjaannya di Gudang 1. Temuan QA P4-02.

    Sekarang "operator Gudang 1" berarti: dicatat oleh SEORANG OPERATOR (siapa
    pun, di gudang mana pun ia berprofil hari ini) dan catatannya MILIK
    Gudang 1. Catatan yang gudangnya tak diketahui tak pernah tersapu.
    """

    actor_ids: list[int] | None
    gudang: str | None = None
    label: str | None = None


async def cakupan(
    db: AsyncSession, *, scope: str | None, nama: str | None, self_id: int,
) -> Cakupan:
    """Terjemahkan pilihan di layar ('saya', 'operator_gudang1', nama, …)."""
    if nama:
        ids = (
            await db.execute(
                select(User.id).where(func.lower(User.nama).like(f"%{nama.lower()}%"))
            )
        ).scalars().all()
        if not ids:
            raise UndoError(f"Pengguna '{nama}' tidak ditemukan.")
        return Cakupan(list(ids), label=f"'{nama}'")
    if scope in (None, "saya"):
        return Cakupan([self_id])
    if scope == "semua":
        return Cakupan(None, label="semua")
    q = select(User.id)
    if scope.startswith("operator"):
        # Semua operator — gudang tempat ia berprofil hari ini BUKAN saringan;
        # gudang catatannya yang menyaring, lewat `Cakupan.gudang`.
        q = q.where(User.role == _P.OPERATOR)
    ids = (await db.execute(q)).scalars().all()
    return Cakupan(list(ids), gudang=_SCOPE_GUDANG.get(scope),
                   label=_SCOPE_LABEL.get(scope, scope))


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


async def _ambil_termasuk_batal(db: AsyncSession, model, id_: int):
    """Baris cermin TERMASUK yang sudah dibatalkan — saringan sesi dilewati,
    supaya pembatalan ganda bisa dijawab 'sudah dibatalkan', bukan 'tak ada'."""
    from app.models.cermin import TERMASUK_DIBATALKAN

    return (await db.execute(
        select(model).where(model.id == id_).execution_options(**{TERMASUK_DIBATALKAN: True})
    )).scalars().first()


async def _undo_purchase(db: AsyncSession, batch_id: int) -> str:
    b = await _ambil_termasuk_batal(db, PurchaseBatch, batch_id)
    if b is None:
        raise UndoError("Batch sudah tidak ada.")
    if b.dibatalkan_pada is not None:
        raise UndoError(f"{b.kode_batch} sudah dibatalkan sebelumnya.")
    if b.status_batch != "baru":
        raise UndoError(f"{b.kode_batch} sudah diproses ({b.status_batch}) — tidak bisa dibatalkan.")
    in_lot = (
        await db.execute(select(DryingLotBatch.id).where(DryingLotBatch.purchase_batch_id == batch_id))
    ).first()
    if in_lot:
        raise UndoError(f"{b.kode_batch} sudah masuk lot pengeringan — tidak bisa dibatalkan.")
    kode = b.kode_batch
    if b.peristiwa_id is not None:
        # ── Jalur peristiwa (Tahap 3): pembatalan = peristiwa LAWAN ──
        #
        # Buku besar tak pernah kehilangan apa pun: `gabah_masuk` tetap ada,
        # `gabah_masuk_dibatalkan` menunjuknya, dan proyeksinya ditandai.
        from app.models.peristiwa import GABAH_MASUK_DIBATALKAN
        from app.services import peristiwa as buku

        await buku.batalkan(db, jenis_lawan=GABAH_MASUK_DIBATALKAN, peristiwa_id=b.peristiwa_id,
                            pelaku_id=None, muatan={"kode_batch": kode,
                                                    "alasan": "Dibatalkan lewat Batalkan input terakhir"})
    # Cermin BERTANDA, bukan dihapus: pembaca menyaringnya lewat
    # `app/models/cermin.py`, dan tiketnya bebas dicatat lagi (indeks parsial).
    from app.database import now_local as _now
    b.dibatalkan_pada = _now()
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
    # ── Klaim silonya dilepas DI SINI, bukan diserahkan ke FK ──
    #
    # `ON DELETE SET NULL` memang melepaskannya juga, tetapi hanya di Postgres
    # dan hanya bila FK-nya masih ada. Pembatalan yang mengembalikan separuh
    # keadaan lebih buruk daripada pembatalan yang menolak: silo yang klaimnya
    # tertinggal tak bisa digiling lagi oleh siapa pun, dan tak ada satu pun
    # kalimat di layar yang menyebutkan sebabnya.
    await db.execute(
        update(SiloStorage).where(SiloStorage.milling_process_id == proc_id)
        .values(milling_process_id=None))
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

    # ── SELURUH silo sumber dikembalikan, bukan penunjuk tunggalnya ──
    #
    # Sejak satu lot boleh datang dari beberapa silo (keputusan pemilik 24
    # September 2026), `proc.silo_storage_id` dan `proc.silo_id` menyebut SALAH
    # SATU. Membatalkan lewat keduanya mengembalikan silo pertama dan
    # meninggalkan silo kedua kosong — padahal gabahnya kembali dianggap belum
    # tergiling. Pembatalan yang mengembalikan separuh keadaan lebih buruk
    # daripada pembatalan yang menolak: tak ada satu pun layar yang menyebut
    # separuh mana yang tertinggal.
    #
    # Klaimnya ikut DIPASANG KEMBALI: prosesnya kembali berstatus 'proses',
    # jadi barisnya kembali "ada di dalam mesin" — tanpa itu, silo yang sama
    # bisa diklaim proses kedua sementara yang pertama masih terbuka.
    from app.models import MillingProcessSource
    from app.penggilingan.gudang1.services.silo import silo_ids_proses

    ids = [x for x in (await db.execute(
        select(MillingProcessSource.silo_storage_id).where(
            MillingProcessSource.milling_process_id == proc_id)
    )).scalars().all() if x]
    if not ids and proc.silo_storage_id:
        ids = [proc.silo_storage_id]      # proses lama, sebelum ada tabel sumber
    for sid in ids:
        st = await db.get(SiloStorage, sid)
        if st:
            st.status = "terisi"
            st.tanggal_keluar = None
            st.milling_process_id = proc_id
    for silo_id in await silo_ids_proses(db, proc):
        silo = await db.get(Silo, silo_id)
        if silo:
            silo.status = "terisi"

    # ── Status batch: SELURUH sumbernya juga ──
    #
    # `selesai_giling` menandai "digiling" setiap batch yang ikut, termasuk yang
    # datang lewat lot pengeringan dan yang masuk saat giling berjalan (QA
    # P-K-18). Yang dikembalikan di sini dulu hanya dua penunjuk tunggal, jadi
    # batch lain tetap berstatus "digiling" sesudah pembatalan — gabah yang
    # kembali ke silo tetapi tak bisa digiling lagi karena ia sudah "digiling".
    lots = {proc.drying_lot_id} if proc.drying_lot_id else set()
    batches = {proc.purchase_batch_id} if proc.purchase_batch_id else set()
    for lot_id, batch_id in (await db.execute(
        select(MillingProcessSource.drying_lot_id,
               MillingProcessSource.purchase_batch_id)
        .where(MillingProcessSource.milling_process_id == proc_id)
    )).all():
        if lot_id:
            lots.add(lot_id)
        if batch_id:
            batches.add(batch_id)
    for lot_id in {x for x in lots if x}:
        await _revert_lot_batches(db, lot_id, "di_silo")
    for batch_id in {x for x in batches if x}:
        b = await db.get(PurchaseBatch, batch_id)
        if b:
            b.status_batch = "di_silo"
    return f"✓ Dibatalkan: selesai giling {proc.kode_proses} (kembali 'proses', silo terisi lagi)."


async def _undo_transfer(db: AsyncSession, transfer_id: int) -> str:
    """Batalkan transfer PK ke Gudang 2 — stok siap kirim kembali bertambah."""
    t = await db.get(InternalTransfer, transfer_id)
    if t is None:
        raise UndoError("Transfer sudah tidak ada.")
    if t.status != "terkirim":
        raise UndoError(f"Transfer {t.kode_transfer} sudah dibatalkan sebelumnya.")
    proc = await db.get(MillingProcess, t.milling_process_id)
    kode = proc.kode_proses if proc else ""
    berat = float(t.berat_kg)
    label = await _label_g2(db, t.lokasi_tujuan, t.silo_id)
    # ── Transfer + pemasukan = SATU pembatalan (P-K-10) ──
    #
    # PK-nya sudah ada di Gudang 2. Pemasukannya lewat penjaga hilir yang
    # sama dengan aksi "Masukkan PK": bila silonya sudah dipoles atau
    # tumpukannya sudah dipindah, seluruh pembatalan ditolak — bukan
    # transfernya hilang sementara PK-nya tetap terhitung di sebelah.
    it = (await db.execute(
        select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id == t.id)
    )).scalars().first()
    if it is not None:
        await _undo_pk_intake(db, it.id, lewat_transfer=True)
    if t.peristiwa_id is not None:
        from app.models.peristiwa import PK_DIPINDAH_G1G2_DIBATALKAN
        from app.services import peristiwa as buku

        await buku.batalkan(db, jenis_lawan=PK_DIPINDAH_G1G2_DIBATALKAN, peristiwa_id=t.peristiwa_id,
                            pelaku_id=None, muatan={"kode_transfer": t.kode_transfer, "berat_kg": berat,
                                                    "alasan": "Dibatalkan lewat Batalkan input terakhir"})
    # Cermin TIDAK dihapus: `_transferred_pk` dan pembaca lain menyaring
    # status `terkirim`, jadi menandainya sudah mengembalikan saldo.
    t.status = "dibatalkan"
    kg = f"{berat:,.0f} kg".replace(",", ".")
    return (
        f"✓ Dibatalkan: transfer {t.kode_transfer} ({kg} PK dari {kode} → "
        f"{label} Gudang 2). Stok siap kirim {kode} kembali bertambah."
    ).strip()


async def _label_g2(db: AsyncSession, tujuan: str | None, silo_id: int | None) -> str:
    """Nama tempat PK di Gudang 2, dibaca dari MASTER.

    Dulu dua kamus di berkas ini memetakan `silo_a`/`silo_b` ke namanya. Kamus
    seperti itu diam saja pada silo ketiga — `.get` mengembalikan kata mentah,
    jadi kalimat pembatalan berbunyi "dimasukkan ke silo_c". Migrasi 0057.
    """
    from app.penggilingan.gudang2.service import label_tujuan

    return await label_tujuan(db, tujuan, silo_id)


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
    b = await _ambil_termasuk_batal(db, PkPurchaseBatch, batch_id)
    if b is None:
        raise UndoError("PK luar sudah tidak ada.")
    if b.dibatalkan_pada is not None:
        raise UndoError(f"{b.kode_batch} sudah dibatalkan sebelumnya.")
    intake = (
        await db.execute(
            select(PkGudang2Intake.id).where(PkGudang2Intake.pk_purchase_batch_id == batch_id)
        )
    ).first()
    if intake:
        raise UndoError(
            f"{b.kode_batch} sudah dimasukkan ke silo/tumpukan — batalkan pemasukannya dulu."
        )
    kode = b.kode_batch
    if b.peristiwa_id is not None:
        # Jalur peristiwa (Tahap 3): pembatalan = peristiwa LAWAN.
        from app.models.peristiwa import PK_LUAR_MASUK_DIBATALKAN
        from app.services import peristiwa as buku

        await buku.batalkan(db, jenis_lawan=PK_LUAR_MASUK_DIBATALKAN, peristiwa_id=b.peristiwa_id,
                            pelaku_id=None, muatan={"kode_batch": kode,
                                                    "alasan": "Dibatalkan lewat Batalkan input terakhir"})
    from app.database import now_local as _now
    b.dibatalkan_pada = _now()   # cermin bertanda, bukan dihapus
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


async def _undo_pk_intake(db: AsyncSession, intake_id: int, *, lewat_transfer: bool = False) -> str:
    it = await _ambil_termasuk_batal(db, PkGudang2Intake, intake_id)
    if it is None:
        raise UndoError("Pemasukan PK sudah tidak ada.")
    if it.dibatalkan_pada is not None:
        raise UndoError("Pemasukan PK itu sudah dibatalkan sebelumnya.")
    # Pemasukan yang lahir dari TRANSFER G1 → G2 tak berdiri sendiri: yang
    # dibatalkan adalah pemindahannya, dan pemasukannya ikut (P-K-10:
    # transfer + pemasukan = satu pembatalan). "Batalkan input terakhir"
    # menemukan jejak pemasukan karena ia ditulis terakhir — dialihkan.
    if it.internal_transfer_id is not None and not lewat_transfer:
        return await _undo_transfer(db, it.internal_transfer_id)
    lok = await _label_g2(db, it.tujuan, it.silo_id)
    await _tolak_bila_pk_sudah_dipakai(db, it, lok)
    b = await db.get(PkPurchaseBatch, it.pk_purchase_batch_id) if it.pk_purchase_batch_id else None
    if it.peristiwa_id is not None:
        from app.models.peristiwa import PK_MASUK_G2_DIBATALKAN
        from app.services import peristiwa as buku

        await buku.batalkan(db, jenis_lawan=PK_MASUK_G2_DIBATALKAN, peristiwa_id=it.peristiwa_id,
                            pelaku_id=None, muatan={"tujuan": it.tujuan,
                                                    "silo_id": it.silo_id,
                                                    "berat_kg": (float(it.berat_kg) if it.berat_kg is not None else None),
                                                    "alasan": "Dibatalkan lewat Batalkan input terakhir"})
    from app.database import now_local as _now
    it.dibatalkan_pada = _now()   # cermin bertanda, bukan dihapus
    if b:
        b.status_batch = "diterima"  # kembali ke 'sudah masuk, belum ditempatkan'
        return f"✓ Dibatalkan: PK {b.kode_batch} dimasukkan ke {lok}."
    return f"✓ Dibatalkan: pemasukan PK ke {lok}."


async def _tolak_bila_silo_dipakai(db: AsyncSession, silo_id: int, sejak, lok: str) -> None:
    """Silo dipoles SESUDAH `sejak`, atau sedang dipoles → tolak (P-K-10)."""
    from sqlalchemy import or_

    from app.models import PolishingProcess, PolishingSiloUsage

    kode = (await db.execute(
        select(PolishingProcess.kode_proses)
        .join(PolishingSiloUsage, PolishingSiloUsage.polishing_process_id == PolishingProcess.id)
        .where(PolishingSiloUsage.silo_id == silo_id,
               or_(PolishingProcess.waktu_mulai >= sejak,
                   PolishingSiloUsage.berat_akhir_kg.is_(None)))
        .order_by(PolishingProcess.id.desc()).limit(1)
    )).scalars().first()
    if kode is not None:
        raise UndoError(
            f"Tak bisa dibatalkan: {lok} sudah dipoles sesudah PK ini masuk "
            f"(penyosohan {kode}). Membatalkannya membuat stok silo minus. "
            "Perbaiki lewat koreksi, atau batalkan penyosohannya lebih dulu.")


async def _undo_pindah_tumpukan(db: AsyncSession, move_id: int) -> str:
    """Batalkan pindah tumpukan → silo: PK kembali ke tumpukan (P-K-10 dijaga)."""
    from app.models import PkTumpukanToSilo, Silo

    m = await _ambil_termasuk_batal(db, PkTumpukanToSilo, move_id)
    if m is None:
        raise UndoError("Pemindahan itu sudah tidak ada.")
    if m.dibatalkan_pada is not None:
        raise UndoError(f"Pemindahan {m.kode_pindah} sudah dibatalkan sebelumnya.")
    silo = await db.get(Silo, m.silo_id)
    lok = silo.nama_silo if silo else f"silo #{m.silo_id}"
    await _tolak_bila_silo_dipakai(db, m.silo_id, m.waktu, lok)
    if m.peristiwa_id is not None:
        from app.models.peristiwa import PK_TUMPUKAN_KE_SILO_DIBATALKAN
        from app.services import peristiwa as buku

        await buku.batalkan(db, jenis_lawan=PK_TUMPUKAN_KE_SILO_DIBATALKAN, peristiwa_id=m.peristiwa_id,
                            pelaku_id=None, muatan={"kode_pindah": m.kode_pindah, "berat_kg": float(m.berat_kg),
                                                    "alasan": "Dibatalkan lewat Batalkan input terakhir"})
    kode, kg = m.kode_pindah, float(m.berat_kg)
    from app.database import now_local as _now
    m.dibatalkan_pada = _now()   # cermin bertanda, bukan dihapus
    return f"✓ Dibatalkan: pemindahan {kode} ({kg:,.0f} kg) — PK kembali ke tumpukan.".replace(",", ".")


async def _tolak_bila_pk_sudah_dipakai(db: AsyncSession, it: PkGudang2Intake, lok: str) -> None:
    """Pemasukan PK yang sudah DIPAKAI di hilir tak boleh dibatalkan — P-K-10.

    Dua rupa pemakaian, keduanya pernah membuat angka bohong:
      · silo-nya dipoles sesudah PK ini masuk (atau sedang dipoles: PK-nya
        sudah ikut dihitung sebagai bahan proses lewat `berat_masuk_kg`) —
        membatalkan pemasukannya membuat stok silo −7.000 kg (r07-E);
      · tumpukannya sudah dipindah (sebagian) ke silo — beratnya lenyap dari
        dua tempat sekaligus (r08-A).
    Yang benar: batalkan/koreksi pekerjaan hilirnya dulu, atau catat koreksi.
    """
    from app.models import PkTumpukanToSilo

    if it.silo_id is not None:
        await _tolak_bila_silo_dipakai(db, it.silo_id, it.waktu_masuk, lok)
    else:
        kode = (await db.execute(
            select(PkTumpukanToSilo.kode_pindah)
            .where(PkTumpukanToSilo.pk_gudang2_intake_id == it.id).limit(1)
        )).scalars().first()
        if kode is not None:
            raise UndoError(
                f"Tak bisa dibatalkan: PK ini sudah dipindah dari tumpukan ke silo "
                f"({kode}). Batalkan pemindahannya dulu.")


#: Tag aksi → penangan pembatalan. Disebut saat aksinya DIBUAT, jadi tak ada
#: yang perlu ditebak saat membatalkan.
_PENANGAN_TAG = {
    "ubah_target": "_undo_ubah_target",
    "betulkan_bobot": "_undo_betulkan_bobot",
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
    if tag == "betulkan_bobot":
        return await _undo_betulkan_bobot(db, log)
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
    if t == "pk_tumpukan_to_silo" and act == "INSERT":
        return await _undo_pindah_tumpukan(db, rid)
    raise UndoError(
        f"Tindakan terakhir ({_TABLE_LABEL.get(t, t)}) belum bisa di-undo otomatis — "
        "fitur menyusul. Untuk sekarang koreksi lewat admin."
    )


async def _undo_betulkan_bobot(db: AsyncSession, log: ActivityLog) -> str:
    """Kembalikan bobot masuk giling ke cuplikan sebelum admin membetulkannya.

    Tanpa tag ia jatuh ke `_undo_finish_milling` — UPDATE pada
    `milling_process` — dan yang terjadi adalah giling yang sudah ditutup
    dibuka lagi, sementara bobotnya tetap yang baru. Dua kerusakan dari satu
    ketukan; pola yang sama dengan `ubah_target`.
    """
    from app.penggilingan.gudang1.services.koreksi_bobot import (
        KoreksiError, kembalikan_bobot_masuk)

    try:
        return await kembalikan_bobot_masuk(db, log.record_id, log.old_value)
    except KoreksiError as e:
        raise UndoError(str(e))


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


async def _log_terakhir(db: AsyncSession, cakupan: Cakupan | None):
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
    if cakupan is not None and cakupan.actor_ids is not None:
        if not cakupan.actor_ids:
            raise UndoError("Tidak ada pengguna yang cocok untuk di-undo.")
        q = q.where(ActivityLog.changed_by.in_(cakupan.actor_ids))
    if cakupan is not None and cakupan.gudang is not None:
        # Gudang CATATAN, bukan gudang orangnya hari ini. NULL tak pernah
        # cocok — catatan yang gudangnya tak diketahui tak tersapu.
        q = q.where(ActivityLog.gudang == cakupan.gudang)
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
    db: AsyncSession, *, cakupan: Cakupan | None
) -> Pratinjau | None:
    """Lihat tindakan terakhir tanpa menyentuhnya. None = tidak ada.

    Jalur bot langsung membatalkan lalu memberi tahu apa yang barusan hilang.
    Di layar itu tidak cukup: tombol yang tidak menyebutkan akibatnya akan
    ditekan untuk mencoba-coba. Karena itu yang ditawarkan adalah kalimat
    lengkapnya, dan yang ditekan orang adalah kalimat itu.
    """
    log = await _log_terakhir(db, cakupan)
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
    db: AsyncSession, *, actor, cakupan: Cakupan | None, log_id: int | None = None,
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

        # ── Barisnya diuji terhadap CAKUPAN, bukan cuma terhadap "terbaru" ──
        #
        # Diambil dengan id saja, dan sampai 25 September 2026 cakupan tak
        # pernah dikenakan padanya: satu-satunya pagar yang tersisa adalah
        # perbandingan dengan `terbaru` di bawah — DAN PAGAR ITU DILEWATI
        # KETIKA `terbaru is None`. Akibatnya terbalik dari yang masuk akal:
        # semakin KOSONG lingkup seseorang, semakin bebas ia membatalkan
        # pekerjaan orang lain. Operator yang belum mencatat apa pun hari ini
        # adalah yang paling leluasa. Temuan QA.
        #
        # `aksi_undo` memang memeriksa NAMA lingkup yang diminta ("Anda hanya
        # boleh membatalkan input Anda sendiri"), dan komentarnya menuliskan
        # niatnya terang-terangan: "daftar itu disaring untuk kenyamanan, dan
        # kenyamanan bukan pengamanan". Nama lingkupnya diperiksa; id lognya
        # tidak — dan id log adalah bilangan kecil berurutan.
        #
        # Kalimat penolakannya SENGAJA tak menyebut lot, nama, atau apa pun
        # dari catatan itu: yang menekan tak berhak melihatnya, dan pesan
        # galat adalah cara termurah membocorkan isi daftar orang lain.
        if cakupan is not None:
            if cakupan.actor_ids is not None and log.changed_by not in cakupan.actor_ids:
                raise UndoError("Tindakan itu bukan input Anda.")
            if cakupan.gudang is not None and log.gudang != cakupan.gudang:
                raise UndoError("Tindakan itu bukan input Anda.")

        terbaru = await _log_terakhir(db, cakupan)
        if terbaru is not None and terbaru.id != log.id:
            raise UndoError(
                f"Sudah berubah: yang terakhir sekarang "
                f"'{(terbaru.new_value or '').split('|')[0].strip()[:50]}'. "
                "Buka lagi daftarnya supaya yang dibatalkan benar-benar yang "
                "Anda maksud."
            )
    else:
        log = await _log_terakhir(db, cakupan)
    if log is None:
        label = cakupan.label if cakupan is not None else None
        suffix = f" oleh {label}" if label else ""
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
