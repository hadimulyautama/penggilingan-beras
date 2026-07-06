"""Logika bisnis silo Gudang 1 (penyimpanan gabah kering)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time, now_local
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
from app.services.codegen import next_drying_lot_code


def _silo_cap_kg(silo) -> float | None:
    return float(silo.kapasitas_ton) * 1000 if silo.kapasitas_ton is not None else None


def _ensure_cap(silo, nama: str, existing_kg: float, new_kg: float) -> None:
    cap = _silo_cap_kg(silo)
    if cap is not None and existing_kg + new_kg > cap:
        sisa = max(cap - existing_kg, 0)
        raise SiloError(
            f"❌ Kapasitas Silo {nama} {cap / 1000:g} ton tidak cukup "
            f"(sisa {sisa / 1000:g} ton, tambahan {new_kg / 1000:g} ton)."
        )


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


async def _silo_active_rows(db: AsyncSession, silo_id: int) -> list[SiloStorage]:
    """Semua penyimpanan aktif (terisi) di silo — bisa >1 baris untuk kering
    yang menunggu (tiap batch 1 baris, tanpa lot)."""
    return list(
        (
            await db.execute(
                select(SiloStorage).where(
                    SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
                )
            )
        ).scalars().all()
    )


async def _row_kg(db: AsyncSession, row: SiloStorage) -> float:
    if row.drying_lot_id:
        return await _lot_kg(db, row.drying_lot_id)
    if row.purchase_batch_id:
        b = await db.get(PurchaseBatch, row.purchase_batch_id)
        return float(b.berat_total_kg) if b else 0.0
    return 0.0


async def _silo_content_kg(db: AsyncSession, silo_id: int) -> float:
    return sum([await _row_kg(db, r) for r in await _silo_active_rows(db, silo_id)])


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
    digabung: bool = False  # True bila batch kering digabung ke lot silo yang ada


async def masuk_silo(
    db: AsyncSession,
    *,
    user,
    nama_silo: str | None,
    kode_lot: str | None,
    kode_batch: str | None,
    tanggal=None, jam=None,
) -> MasukResult:
    if not nama_silo:
        raise SiloError("Sebutkan silo A atau B, contoh: `masukkan LOT-... ke silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise SiloError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    occupied = await _active_storage(db, silo.id)
    now = input_time(tanggal, jam)
    digabung = False

    if kode_lot:
        # ── Dari pengeringan: 1 silo = 1 lot. Silo harus kosong. ──
        if occupied:
            raise SiloError(f"Silo {nama_silo} sudah terisi — kosongkan dulu.")
        lot = (
            await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode_lot))
        ).scalars().first()
        if lot is None:
            raise SiloError(f"Lot {kode_lot} tidak ditemukan.")
        if lot.status != "selesai":
            raise SiloError(f"Lot {kode_lot} belum selesai dikeringkan.")
        # Pendinginan SELESAI harus dinyatakan operator DULU (bukan dipicu oleh
        # pemindahan ini) — supaya downtime dryer terukur: lot bisa selesai dingin
        # sambil tetap di dryer menunggu silo kosong.
        if lot.waktu_selesai_pendinginan is None:
            raise SiloError(
                f"Lot {kode_lot} belum dinyatakan selesai pendinginan. "
                f"Nyatakan `pendinginan selesai {kode_lot}` dulu."
            )
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
        _ensure_cap(silo, nama_silo, 0, kg)
        db.add(
            SiloStorage(
                silo_id=silo.id, drying_lot_id=lot.id, tipe_masuk="dari_pengeringan",
                tanggal_masuk=now, input_by=user.id, status="terisi",
            )
        )
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
        # Pendinginan sudah dinyatakan selesai (dijaga di atas) — pindah ini
        # murni perpindahan fisik dryer → silo, tidak menyentuh waktu pendinginan.
        isi, tipe = kode_lot, "dari_pengeringan"

    elif kode_batch:
        # ── Gabah kering langsung: batch jadi lot di silo; boleh menumpuk. ──
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
                select(DryingLotBatch.id).where(DryingLotBatch.purchase_batch_id == batch.id)
            )
        ).first()
        if in_lot or batch.status_batch == "di_silo":
            raise SiloError(f"Batch {kode_batch} sudah masuk lot/silo.")
        kg_new = float(batch.berat_total_kg)

        # Model baru: kering MENUNGGU lepas di silo (SiloStorage batch, TANPA lot).
        # Lot dibentuk saat 'giling silo X'. Boleh menumpuk sampai kapasitas silo.
        rows = await _silo_active_rows(db, silo.id)
        if any(r.tipe_masuk == "dari_pengeringan" for r in rows):
            raise SiloError(
                f"Silo {nama_silo} berisi lot pengeringan — tidak bisa dicampur "
                "gabah kering langsung. Pakai silo lain."
            )
        existing_kg = await _silo_content_kg(db, silo.id)
        _ensure_cap(silo, nama_silo, existing_kg, kg_new)
        db.add(
            SiloStorage(
                silo_id=silo.id, purchase_batch_id=batch.id, drying_lot_id=None,
                tipe_masuk="langsung_kering", tanggal_masuk=now,
                input_by=user.id, status="terisi",
            )
        )
        batch.status_batch = "di_silo"
        digabung = bool(rows)  # sudah ada kering menunggu sebelumnya
        isi, tipe = batch.kode_batch, "langsung_kering"
        kg = existing_kg + kg_new
    else:
        raise SiloError(
            "Sebutkan lot atau batch yang dimasukkan, contoh:\n"
            "`masukkan LOT-20260702-01 ke silo A`"
        )

    silo.status = "terisi"
    # Gabung ke lot silo dicatat sebagai UPDATE 'gabung' agar undo hanya
    # melepas batch terakhir (bukan menghapus seluruh isi silo).
    await log_activity(
        db,
        table_name="silo_storage",
        record_id=silo.id,
        action="UPDATE" if digabung else "INSERT",
        field_name="gabung" if digabung else None,
        changed_by=user.id,
        new_value=f"Silo {nama_silo} <- {isi} ({tipe}{'+gabung' if digabung else ''}, {kg:.0f}kg)",
    )
    await db.commit()
    return MasukResult(nama_silo=nama_silo, isi=isi, kg=kg, tipe=tipe, digabung=digabung)


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
    now = now_local()
    ml = SiloMovingLog(
        drying_lot_id=lot.id,
        silo_id=silo.id if silo else None,
        tipe="mulai",
        waktu=now,
        input_by=user.id,
    )
    db.add(ml)
    await db.flush()
    # CATATAN: pendinginan selesai TIDAK diset di sini — itu keputusan operator
    # terpisah (`pendinginan selesai LOT-...`) demi ukuran downtime dryer.
    await log_activity(
        db, table_name="silo_moving_logs", record_id=ml.id, action="INSERT",
        changed_by=user.id, new_value=f"mulai pindah {lot.kode_lot}",
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

    # Bila silo tujuan tak disebut ("pemindahan selesai"), ambil dari log
    # 'mulai pindah' sebelumnya.
    if not nama_silo:
        ml_mulai = (
            await db.execute(
                select(SiloMovingLog)
                .where(
                    SiloMovingLog.drying_lot_id == lot.id,
                    SiloMovingLog.tipe == "mulai",
                    SiloMovingLog.silo_id.is_not(None),
                )
                .order_by(SiloMovingLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if ml_mulai:
            silo_mulai = await db.get(Silo, ml_mulai.silo_id)
            if silo_mulai:
                nama_silo = silo_mulai.nama_silo.replace("Silo ", "")

    existing = await _lot_active_storage(db, lot.id)
    if existing:
        # Sudah tercatat di silo -> cukup log 'selesai'.
        silo = await db.get(Silo, existing.silo_id)
        ml = SiloMovingLog(
            drying_lot_id=lot.id, silo_id=existing.silo_id, tipe="selesai",
            waktu=now_local(), input_by=user.id,
        )
        db.add(ml)
        await db.flush()
        await log_activity(
            db, table_name="silo_moving_logs", record_id=ml.id, action="INSERT",
            changed_by=user.id, new_value=f"selesai pindah {lot.kode_lot}",
        )
        await db.commit()
        nama = silo.nama_silo.replace("Silo ", "") if silo else "-"
        return MovingDoneResult(kode_lot=lot.kode_lot, nama_silo=nama, kondisi="already", kg=None)

    # Belum di silo -> lakukan intake (state: di silo + dryer kosong).
    res = await masuk_silo(db, user=user, nama_silo=nama_silo, kode_lot=kode_lot, kode_batch=None)
    silo = await get_g1_silo(db, res.nama_silo)
    ml = SiloMovingLog(
        drying_lot_id=lot.id, silo_id=silo.id if silo else None, tipe="selesai",
        waktu=now_local(), input_by=user.id,
    )
    db.add(ml)
    await db.flush()
    await log_activity(
        db, table_name="silo_moving_logs", record_id=ml.id, action="INSERT",
        changed_by=user.id, new_value=f"selesai pindah {lot.kode_lot} (intake)",
    )
    await db.commit()
    return MovingDoneResult(
        kode_lot=lot.kode_lot, nama_silo=res.nama_silo, kondisi="intake", kg=res.kg
    )


# ─────────────────────────── Keluar silo ───────────────────────────
async def keluar_silo(db: AsyncSession, *, user, nama_silo: str | None, tanggal=None, jam=None) -> str:
    if not nama_silo:
        raise SiloError("Sebutkan silo yang dikosongkan, contoh: `kosongkan silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise SiloError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    storage = await _active_storage(db, silo.id)
    if storage is None:
        raise SiloError(f"Silo {nama_silo} sudah kosong.")
    keluar = input_time(tanggal, jam)
    if storage.tanggal_masuk and keluar < storage.tanggal_masuk:
        raise SiloError(
            f"Tanggal keluar lebih awal dari masuk silo "
            f"({storage.tanggal_masuk:%d-%m-%Y %H:%M})."
        )
    storage.status = "kosong"
    storage.tanggal_keluar = keluar
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
async def laporan_silo(db: AsyncSession, nama_silo: str | None = None) -> str:
    """Status silo Gudang 1 (isi, supplier, kapasitas). `nama_silo` mem-filter
    ke satu silo (mis. 'A') bila disebut."""
    wid = await _g1_warehouse_id(db)
    stmt = select(Silo).where(Silo.warehouse_id == wid)
    if nama_silo:
        stmt = stmt.where(func.upper(Silo.nama_silo).like(f"%{nama_silo.upper()}%"))
    silos = (await db.execute(stmt.order_by(Silo.nama_silo))).scalars().all()
    if not silos:
        if nama_silo:
            return f"Silo {nama_silo} tidak ditemukan di Gudang 1."
        return "Belum ada silo di Gudang 1."
    now = now_local()
    judul = f"🏗️ Status Silo {nama_silo}:" if nama_silo else "🏗️ Status silo Gudang 1:"
    lines = [judul]
    for silo in silos:
        cap = (
            f"maks {float(silo.kapasitas_ton):g} ton"
            if silo.kapasitas_ton is not None
            else "kapasitas belum diatur"
        )
        rows = await _silo_active_rows(db, silo.id)
        if not rows:
            lines.append(f"• {silo.nama_silo}: kosong ({cap})")
            continue
        lot_row = next((r for r in rows if r.drying_lot_id), None)
        if lot_row is not None:
            jam = (now - lot_row.tanggal_masuk).total_seconds() / 3600
            lot = await db.get(DryingLot, lot_row.drying_lot_id)
            kg = await _lot_kg(db, lot_row.drying_lot_id)
            sups = ", ".join(await _lot_suppliers(db, lot_row.drying_lot_id)) or "-"
            isi = f"{lot.kode_lot if lot else 'lot'} ({sups})"
            lines.append(
                f"• {silo.nama_silo}: terisi — {isi}, {_fmt_kg(kg)}, {jam:.0f} jam ({cap})"
            )
        else:
            # Kering MENUNGGU (belum jadi lot — lot dibentuk saat digiling).
            kodes, total = [], 0.0
            for r in rows:
                b = await db.get(PurchaseBatch, r.purchase_batch_id)
                if b:
                    kodes.append(b.kode_batch)
                    total += float(b.berat_total_kg)
            lines.append(
                f"• {silo.nama_silo}: kering menunggu — {len(kodes)} batch "
                f"({', '.join(kodes)}), {_fmt_kg(total)} ({cap}).\n"
                f"  _Ketik `giling {silo.nama_silo}` untuk membentuk lot & giling._"
            )
    return "\n".join(lines)
