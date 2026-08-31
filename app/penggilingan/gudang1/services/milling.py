"""Logika bisnis proses milling / pecah kulit (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time, now_local
from app.models import (
    DryingLot,
    DryingLotBatch,
    InternalTransfer,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    Silo,
    SiloStorage,
    Supplier,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_drying_lot_code, next_milling_code
from app.penggilingan.gudang1.services.silo import _silo_active_rows, get_g1_silo


class MillingError(Exception):
    """Kesalahan proses milling dengan pesan siap-tampil (args[0])."""


async def get_process_by_kode(db: AsyncSession, kode: str) -> MillingProcess | None:
    return (
        await db.execute(select(MillingProcess).where(MillingProcess.kode_proses == kode))
    ).scalars().first()


async def sole_active_milling_kode(db: AsyncSession) -> str | None:
    """Kode proses bila TEPAT ADA SATU milling yang sedang 'proses'; else None.

    Memungkinkan 'giling selesai' / 'progress 5 ton' tanpa menyebut kode.
    """
    rows = (
        await db.execute(
            select(MillingProcess.kode_proses).where(MillingProcess.status == "proses")
        )
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def _storage_kg(db: AsyncSession, st: SiloStorage) -> float:
    if st.drying_lot_id:
        stmt = (
            select(func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0))
            .select_from(DryingLotBatch)
            .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
            .where(DryingLotBatch.drying_lot_id == st.drying_lot_id)
        )
        return float((await db.execute(stmt)).scalar_one())
    if st.purchase_batch_id:
        b = await db.get(PurchaseBatch, st.purchase_batch_id)
        return float(b.berat_total_kg) if b else 0.0
    return 0.0


async def _active_storage(db: AsyncSession, silo_id: int) -> SiloStorage | None:
    return (
        await db.execute(
            select(SiloStorage).where(
                SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
            )
        )
    ).scalars().first()


# ─────────────────────────── Mulai ───────────────────────────
@dataclass
class StartResult:
    proc: MillingProcess
    nama_silo: str
    berat_masuk: float


async def start_milling(
    db: AsyncSession, *, user, nama_silo: str | None, tanggal=None, jam=None
) -> StartResult:
    if not nama_silo:
        raise MillingError("Sebutkan silo mana, contoh: `giling silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise MillingError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    rows = await _silo_active_rows(db, silo.id)
    if not rows:
        raise MillingError(f"Silo {nama_silo} kosong — tidak ada yang bisa digiling.")
    active = (
        await db.execute(
            select(MillingProcess).where(
                MillingProcess.silo_id == silo.id, MillingProcess.status == "proses"
            )
        )
    ).scalars().first()
    if active:
        raise MillingError(f"Silo {nama_silo} sedang digiling ({active.kode_proses}).")

    now = input_time(tanggal, jam)
    lot_row = next((r for r in rows if r.drying_lot_id), None)
    if lot_row is not None:
        st = lot_row  # dari pengeringan: lot sudah ada
    else:
        # KERING menunggu: bentuk 1 LOT dari SEMUA batch di silo saat giling dimulai.
        loose = [r for r in rows if r.purchase_batch_id]
        lot = DryingLot(
            kode_lot=await next_drying_lot_code(db), dryer_id=None,
            waktu_mulai_pengeringan=now, waktu_selesai_pengeringan=now,
            status="selesai", created_by=user.id,
        )
        db.add(lot)
        await db.flush()
        for r in loose:
            db.add(DryingLotBatch(drying_lot_id=lot.id, purchase_batch_id=r.purchase_batch_id))
        st = loose[0]  # konsolidasi: baris pertama jadi lot-row, sisanya ditutup
        st.drying_lot_id = lot.id
        st.purchase_batch_id = None
        for r in loose[1:]:
            r.status = "kosong"
        await db.flush()

    berat = await _storage_kg(db, st)
    proc = MillingProcess(
        kode_proses=await next_milling_code(db),
        silo_id=silo.id,
        silo_storage_id=st.id,
        drying_lot_id=st.drying_lot_id,
        purchase_batch_id=st.purchase_batch_id,
        berat_gabah_masuk_kg=berat,
        waktu_mulai=now,
        status="proses",
        created_by=user.id,
    )
    db.add(proc)
    await db.flush()
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"{proc.kode_proses} <- Silo {nama_silo} ({berat:.0f}kg)",
    )
    await db.commit()
    await db.refresh(proc)
    return StartResult(proc=proc, nama_silo=nama_silo, berat_masuk=berat)


# ─────────────────────────── Progress ───────────────────────────
@dataclass
class ProgressResult:
    proc: MillingProcess
    berat_kumulatif: float
    rendemen_persen: float | None
    jenis: str | None = None  # KS (dari gabah basah) / KL (dari gabah kering)


async def log_progress(
    db: AsyncSession, *, user, kode_proses: str | None, berat_kumulatif: float | None,
    tanggal=None, jam=None,
) -> ProgressResult:
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `progress giling MIL-20260702-01 5 ton`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")
    if berat_kumulatif is None:
        raise MillingError("Sebutkan berat PK kumulatifnya, mis. `MIL-... sudah 5 ton`.")

    db.add(
        MillingProgressLog(
            milling_process_id=proc.id,
            waktu_update=input_time(tanggal, jam),
            berat_kumulatif_kg=berat_kumulatif,
            input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="milling_progress_logs", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"kumulatif {berat_kumulatif:.0f}kg",
    )
    await db.commit()
    masuk = float(proc.berat_gabah_masuk_kg or 0)
    rendemen = (berat_kumulatif / masuk * 100) if masuk else None
    jenis = await pk_jenis(db, proc)
    return ProgressResult(
        proc=proc, berat_kumulatif=berat_kumulatif, rendemen_persen=rendemen, jenis=jenis,
    )


# ─────────────────────────── Selesai (auto-kosongkan silo) ───────────────────────────
@dataclass
class FinishResult:
    proc: MillingProcess
    nama_silo: str | None
    produced: float
    siap_kirim: float
    jenis: str | None = None  # KS / KL


async def finish_milling(
    db: AsyncSession, *, user, kode_proses: str | None, tanggal=None, jam=None
) -> FinishResult:
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `MIL-20260702-01 selesai`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")

    now = input_time(tanggal, jam)
    if now < proc.waktu_mulai:
        raise MillingError(
            f"Tanggal selesai lebih awal dari mulai giling "
            f"({proc.waktu_mulai:%d-%m-%Y %H:%M})."
        )
    proc.status = "selesai"
    proc.waktu_selesai = now

    # Silo dianggap kosong saat milling selesai (bukan saat gabah keluar fisik).
    nama_silo = None
    if proc.silo_storage_id:
        st = await db.get(SiloStorage, proc.silo_storage_id)
        if st and st.status == "terisi":
            st.status = "kosong"
            st.tanggal_keluar = now
        silo = await db.get(Silo, proc.silo_id)
        if silo:
            silo.status = "kosong"
            nama_silo = silo.nama_silo.replace("Silo ", "")
    # Batch sumber berstatus digiling.
    if proc.drying_lot_id:
        bids = (
            await db.execute(
                select(DryingLotBatch.purchase_batch_id).where(
                    DryingLotBatch.drying_lot_id == proc.drying_lot_id
                )
            )
        ).scalars().all()
        for bid in bids:
            b = await db.get(PurchaseBatch, bid)
            if b:
                b.status_batch = "digiling"
    elif proc.purchase_batch_id:
        b = await db.get(PurchaseBatch, proc.purchase_batch_id)
        if b:
            b.status_batch = "digiling"

    bd = await _pk_breakdown(db, proc.id)
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="status", new_value="selesai",
    )
    jenis = await pk_jenis(db, proc)
    await db.commit()
    return FinishResult(
        proc=proc, nama_silo=nama_silo, produced=bd.produced, siap_kirim=bd.tersedia,
        jenis=jenis,
    )


# ─────────────────────────── Laporan ───────────────────────────
async def _latest_progress(db: AsyncSession, proc_id: int) -> float | None:
    v = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc_id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return float(v) if v is not None else None


async def _produced_pk(db: AsyncSession, proc_id: int) -> float:
    """PK dihasilkan = progress kumulatif terakhir (hasil yang di-update operator)."""
    v = await _latest_progress(db, proc_id)
    return float(v) if v is not None else 0.0


async def _transferred_pk(db: AsyncSession, proc_id: int) -> float:
    """Total PK yang SUDAH dikirim (transfer) dari sebuah proses."""
    r = (
        await db.execute(
            select(func.coalesce(func.sum(InternalTransfer.berat_kg), 0)).where(
                InternalTransfer.milling_process_id == proc_id,
                InternalTransfer.status == "terkirim",
            )
        )
    ).scalar_one()
    return float(r)


@dataclass
class PkBreakdown:
    produced: float     # total PK dihasilkan (hasil yang di-update operator)
    transferred: float  # sudah dikirim ke Gudang 2
    tersedia: float     # siap kirim (stok) = produced - transferred


async def _sold_pk_langsung(db: AsyncSession, proc_id: int) -> float:
    """PK yang sudah dijual langsung dari Gudang 1 (barang keluar pk_langsung)."""
    from app.models import OutgoingItem
    r = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(
                OutgoingItem.item_type == "pk_langsung",
                OutgoingItem.milling_process_id == proc_id,
            )
        )
    ).scalar_one()
    return float(r)


async def _pk_breakdown(db: AsyncSession, proc_id: int) -> PkBreakdown:
    """Stok PK siap kirim = hasil − dikirim (transfer) − dijual langsung."""
    produced = await _produced_pk(db, proc_id)
    transferred = await _transferred_pk(db, proc_id)
    sold = await _sold_pk_langsung(db, proc_id)
    return PkBreakdown(produced, transferred, max(produced - transferred - sold, 0.0))


async def _milling_supplier_names(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Supplier asal bahan sebuah proses giling: lewat lot pengeringan (batch
    gabungan) atau batch langsung."""
    if proc.drying_lot_id:
        rows = (
            await db.execute(
                select(Supplier.nama_supplier)
                .join(PurchaseBatch, PurchaseBatch.supplier_id == Supplier.id)
                .join(
                    DryingLotBatch,
                    DryingLotBatch.purchase_batch_id == PurchaseBatch.id,
                )
                .where(DryingLotBatch.drying_lot_id == proc.drying_lot_id)
                .distinct()
            )
        ).scalars().all()
        return list(rows)
    if proc.purchase_batch_id:
        nama = (
            await db.execute(
                select(Supplier.nama_supplier)
                .join(PurchaseBatch, PurchaseBatch.supplier_id == Supplier.id)
                .where(PurchaseBatch.id == proc.purchase_batch_id)
            )
        ).scalars().first()
        return [nama] if nama else []
    return []


async def _source_kondisi(db: AsyncSession, proc: MillingProcess) -> str | None:
    """Kondisi gabah sumber proses: 'basah' / 'kering'. Satu lot tidak boleh
    campur basah & kering, jadi cukup satu batch sumber."""
    if proc.drying_lot_id:
        return (
            await db.execute(
                select(PurchaseBatch.kondisi_gabah)
                .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == proc.drying_lot_id)
                .limit(1)
            )
        ).scalars().first()
    if proc.purchase_batch_id:
        b = await db.get(PurchaseBatch, proc.purchase_batch_id)
        return b.kondisi_gabah if b else None
    return None


async def pk_jenis(db: AsyncSession, proc: MillingProcess) -> str | None:
    """Jenis PK hasil Gudang 1: gabah basah → KS, gabah kering → KL."""
    k = await _source_kondisi(db, proc)
    return {"basah": "KS", "kering": "KL"}.get(k)


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_milling(db: AsyncSession, kode_proses: str | None = None) -> str:
    now = now_local()
    if kode_proses:
        proc = await get_process_by_kode(db, kode_proses)
        if proc is None:
            return f"Proses {kode_proses} tidak ditemukan."
        masuk = float(proc.berat_gabah_masuk_kg or 0)
        prog = await _latest_progress(db, proc.id)
        bd = await _pk_breakdown(db, proc.id)
        suppliers = await _milling_supplier_names(db, proc)
        nama = ", ".join(suppliers) if suppliers else "-"
        asal_lot = ""
        if proc.drying_lot_id:
            lot = await db.get(DryingLot, proc.drying_lot_id)
            if lot:
                asal_lot = f" (via {lot.kode_lot})"
        jenis = await pk_jenis(db, proc)
        jenis_lbl = f" ({jenis})" if jenis else ""
        lines = [
            f"⚙️ Giling {proc.kode_proses} — bahan dari {nama}{asal_lot}",
            f"• Status: {proc.status}",
            f"• Jenis PK: {jenis or '-'}",
            f"• Gabah masuk: {_kg(masuk)}",
            f"• PK dihasilkan: {_kg(bd.produced)}{jenis_lbl}",
            f"• Siap kirim (stok): {_kg(bd.tersedia)}",
        ]
        if bd.transferred > 0:
            lines.append(f"• Sudah dikirim: {_kg(bd.transferred)}")
        if prog is not None and masuk:
            lines.append(f"• Rendemen sementara: {prog / masuk * 100:.1f}%")
        return "\n".join(lines)

    procs = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "proses").order_by(MillingProcess.id)
        )
    ).scalars().all()
    if not procs:
        return "⚙️ Tidak ada proses giling yang sedang berjalan."
    lines = [f"⚙️ Giling berjalan ({len(procs)} proses):"]
    for proc in procs:
        prog = await _latest_progress(db, proc.id)
        jam = (now - proc.waktu_mulai).total_seconds() / 3600
        jenis = await pk_jenis(db, proc)
        jlbl = f" {jenis}" if jenis else ""
        lines.append(
            f"• {proc.kode_proses}: PK{jlbl} {_kg(prog) if prog is not None else '0 kg'} — {jam:.1f} jam"
        )
    return "\n".join(lines)


async def stok_pk_gudang1(db: AsyncSession) -> str:
    """Stok PK siap kirim di Gudang 1 = hasil produksi tiap proses − yang sudah dikirim."""
    procs = (
        await db.execute(
            select(MillingProcess).order_by(MillingProcess.kode_proses)
        )
    ).scalars().all()
    items: list[tuple[str, str | None, PkBreakdown]] = []
    for proc in procs:
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia > 0:
            items.append((proc.kode_proses, await pk_jenis(db, proc), bd))
    if not items:
        return "📦 Stok PK Gudang 1 kosong."
    total = sum(bd.tersedia for _, _, bd in items)
    sub: dict[str, float] = {}
    for _, jenis, bd in items:
        sub[jenis or "?"] = sub.get(jenis or "?", 0.0) + bd.tersedia
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(sub.items()))
    lines = [f"📦 Stok PK siap kirim Gudang 1: {_kg(total)}  ({ringkas})"]
    for kode, jenis, bd in items:
        detail = f"• {jenis or '-'} dari {kode}: {_kg(bd.tersedia)}"
        if bd.transferred > 0:
            detail += f" (dari {_kg(bd.produced)}, terkirim {_kg(bd.transferred)})"
        lines.append(detail)
    return "\n".join(lines)


# ─────────────────────── QC & Verifikasi (staff/admin) ───────────────────────
@dataclass
class QcResult:
    proc: MillingProcess
    kadar_air: float | None
    broken: float | None
    susut: float | None
    kondisi: str | None
    qc_count: int


async def log_qc_milling(
    db: AsyncSession,
    *,
    user,
    kode_proses: str | None,
    kadar_air: float | None,
    broken: float | None,
    susut: float | None,
    kondisi: str | None,
) -> QcResult:
    if not kode_proses:
        raise MillingError(
            "Sebutkan kode proses, contoh: `QC MIL-20260702-01 kadar air 13 broken 5 kondisi KS`"
        )
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if all(v is None for v in (kadar_air, broken, susut)):
        raise MillingError("Sebutkan hasil QC-nya (kadar air / broken / susut).")
    # Jenis PK (KS/KL) TIDAK diisi manual — ditentukan otomatis dari kondisi
    # gabah sumber: basah → KS, kering → KL. Input manual diabaikan.
    kondisi = await pk_jenis(db, proc) or kondisi

    db.add(
        MillingQcLog(
            milling_process_id=proc.id,
            kadar_air=kadar_air,
            broken_persen=broken,
            susut_persen=susut,
            kondisi=kondisi,
            waktu=now_local(),
            input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="milling_qc_logs", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=f"ka={kadar_air} broken={broken} susut={susut} kondisi={kondisi}",
    )
    await db.commit()
    count = (
        await db.execute(
            select(func.count()).select_from(MillingQcLog).where(
                MillingQcLog.milling_process_id == proc.id
            )
        )
    ).scalar_one()
    return QcResult(
        proc=proc, kadar_air=kadar_air, broken=broken, susut=susut,
        kondisi=kondisi, qc_count=count,
    )


@dataclass
class VerifyOutputResult:
    proc: MillingProcess
    berat_output: float
    rendemen_persen: float | None
    re_verified: bool


async def verify_milling_output(
    db: AsyncSession, *, user, kode_proses: str | None, berat_output: float | None
) -> VerifyOutputResult:
    if not kode_proses:
        raise MillingError(
            "Sebutkan kode proses, contoh: `verifikasi output MIL-20260702-01 14 ton`"
        )
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if berat_output is None:
        raise MillingError("Sebutkan berat output PK final-nya, mis. `... 14 ton`.")

    verif = (
        await db.execute(
            select(MillingProcessVerification).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    re_verified = verif is not None
    if verif is None:
        verif = MillingProcessVerification(milling_process_id=proc.id)
        db.add(verif)
    verif.berat_output_final_kg = berat_output
    verif.verified_by = user.id
    verif.waktu_verifikasi = now_local()
    verif.status_verifikasi = "terverifikasi"

    await log_activity(
        db,
        table_name="milling_process_verifications",
        record_id=proc.id,
        action="UPDATE" if re_verified else "INSERT",
        changed_by=user.id,
        field_name="berat_output_final_kg",
        new_value=f"{berat_output:.0f}",
    )
    await db.commit()
    masuk = float(proc.berat_gabah_masuk_kg or 0)
    rendemen = (berat_output / masuk * 100) if masuk else None
    return VerifyOutputResult(
        proc=proc, berat_output=berat_output, rendemen_persen=rendemen, re_verified=re_verified
    )
