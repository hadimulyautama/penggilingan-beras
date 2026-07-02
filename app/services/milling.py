"""Logika bisnis proses milling / pecah kulit (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLotBatch,
    MillingPkRouting,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PkStockGudang1,
    PurchaseBatch,
    Silo,
    SiloStorage,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_milling_code
from app.services.silo import get_g1_silo

BUFFER_MAKS_KG = 30_000  # buffer tumpukan PK Gudang 1 maks 30 ton


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


async def start_milling(db: AsyncSession, *, user, nama_silo: str | None) -> StartResult:
    if not nama_silo:
        raise MillingError("Sebutkan silo mana, contoh: `giling silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise MillingError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    st = await _active_storage(db, silo.id)
    if st is None:
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

    berat = await _storage_kg(db, st)
    now = now_local()
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


async def log_progress(
    db: AsyncSession, *, user, kode_proses: str | None, berat_kumulatif: float | None
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
            waktu_update=now_local(),
            berat_kumulatif_kg=berat_kumulatif,
            input_by=user.id,
        )
    )
    await db.commit()
    masuk = float(proc.berat_gabah_masuk_kg or 0)
    rendemen = (berat_kumulatif / masuk * 100) if masuk else None
    return ProgressResult(proc=proc, berat_kumulatif=berat_kumulatif, rendemen_persen=rendemen)


# ─────────────────────────── Routing ───────────────────────────
@dataclass
class RouteResult:
    proc: MillingProcess
    tujuan: str
    berat: float
    buffer_total: float | None  # total buffer setelah tumpuk


async def route_pk(
    db: AsyncSession, *, user, kode_proses: str | None, berat: float | None, tujuan: str | None
) -> RouteResult:
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `tumpuk 3 ton PK dari MIL-20260702-01`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")
    if berat is None:
        raise MillingError("Sebutkan berat PK-nya, mis. `tumpuk 3 ton dari MIL-...`.")
    if tujuan not in ("tumpuk", "siap_transfer"):
        raise MillingError("Diarahkan ke mana — *tumpuk* atau *siap transfer*?")

    now = now_local()
    db.add(
        MillingPkRouting(
            milling_process_id=proc.id,
            berat_kg=berat,
            tujuan=tujuan,
            status_transfer="menunggu" if tujuan == "siap_transfer" else None,
            waktu=now,
            input_by=user.id,
        )
    )
    buffer_total = None
    if tujuan == "tumpuk":
        stock = (
            await db.execute(
                select(PkStockGudang1).where(PkStockGudang1.milling_process_id == proc.id)
            )
        ).scalars().first()
        if stock is None:
            stock = PkStockGudang1(
                drying_lot_id=proc.drying_lot_id,
                milling_process_id=proc.id,
                berat_kg=0,
                status="tersedia",
            )
            db.add(stock)
        stock.berat_kg = float(stock.berat_kg) + berat

    await log_activity(
        db, table_name="milling_pk_routing", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"{tujuan} {berat:.0f}kg dari {proc.kode_proses}",
    )
    await db.commit()

    if tujuan == "tumpuk":
        buffer_total = float(
            (
                await db.execute(
                    select(func.coalesce(func.sum(PkStockGudang1.berat_kg), 0)).where(
                        PkStockGudang1.status == "tersedia"
                    )
                )
            ).scalar_one()
        )
    return RouteResult(proc=proc, tujuan=tujuan, berat=berat, buffer_total=buffer_total)


# ─────────────────────────── Selesai (auto-kosongkan silo) ───────────────────────────
@dataclass
class FinishResult:
    proc: MillingProcess
    nama_silo: str | None
    total_tumpuk: float
    total_transfer: float


async def finish_milling(db: AsyncSession, *, user, kode_proses: str | None) -> FinishResult:
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `MIL-20260702-01 selesai`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")

    now = now_local()
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

    tot_tumpuk, tot_transfer = await _routing_totals(db, proc.id)
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="status", new_value="selesai",
    )
    await db.commit()
    return FinishResult(proc=proc, nama_silo=nama_silo, total_tumpuk=tot_tumpuk, total_transfer=tot_transfer)


# ─────────────────────────── Laporan ───────────────────────────
async def _routing_totals(db: AsyncSession, proc_id: int) -> tuple[float, float]:
    rows = (
        await db.execute(
            select(MillingPkRouting.tujuan, func.sum(MillingPkRouting.berat_kg))
            .where(MillingPkRouting.milling_process_id == proc_id)
            .group_by(MillingPkRouting.tujuan)
        )
    ).all()
    d = {t: float(s) for t, s in rows}
    return d.get("tumpuk", 0.0), d.get("siap_transfer", 0.0)


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
        tumpuk, transfer = await _routing_totals(db, proc.id)
        lines = [
            f"⚙️ {proc.kode_proses} — status: {proc.status}",
            f"• Gabah masuk: {_kg(masuk)}",
            f"• PK keluar (progress): {_kg(prog) if prog is not None else '-'}",
            f"• Ditumpuk: {_kg(tumpuk)} | Siap transfer: {_kg(transfer)}",
        ]
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
        lines.append(
            f"• {proc.kode_proses}: PK {_kg(prog) if prog is not None else '0 kg'} — {jam:.1f} jam"
        )
    return "\n".join(lines)


async def stok_pk_gudang1(db: AsyncSession) -> str:
    rows = (
        await db.execute(
            select(MillingProcess.kode_proses, PkStockGudang1.berat_kg)
            .join(MillingProcess, PkStockGudang1.milling_process_id == MillingProcess.id)
            .where(PkStockGudang1.status == "tersedia", PkStockGudang1.berat_kg > 0)
            .order_by(MillingProcess.kode_proses)
        )
    ).all()
    if not rows:
        return "📦 Buffer PK Gudang 1 kosong."
    total = sum(float(b) for _, b in rows)
    lines = [f"📦 Stok PK buffer Gudang 1: {_kg(total)} (maks {_kg(BUFFER_MAKS_KG)})"]
    for kode, b in rows:
        lines.append(f"• dari {kode}: {_kg(float(b))}")
    if total > BUFFER_MAKS_KG:
        lines.append("⚠️ Melebihi kapasitas buffer!")
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
    if all(v is None for v in (kadar_air, broken, susut, kondisi)):
        raise MillingError("Sebutkan hasil QC-nya (kadar air / broken / susut / kondisi).")
    if kondisi is not None and kondisi not in ("KS", "KL"):
        raise MillingError("Kondisi harus KS atau KL.")

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
